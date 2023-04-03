import matmul_utils_4bit as mm4b
import torch
import torch.nn as nn
import time
import math


class AutogradMatmul4bit(torch.autograd.Function):

    @staticmethod
    def forward(ctx, x, qweight, scales, zeros, groupsize=-1):
        ctx.save_for_backward(qweight, scales, zeros)
        ctx.groupsize = groupsize
        if groupsize == -1:
            output = mm4b._matmul4bit_v1_recons(x, qweight, scales, zeros)
        else:
            output = mm4b._matmul4bit_v2_recons(x, qweight, scales, zeros, groupsize)
        output = output.clone()
        return output

    @staticmethod
    def backward(ctx, grad_output):
        qweight, scales, zeros = ctx.saved_tensors
        groupsize = ctx.groupsize
        if groupsize == -1:
            grad = mm4b._matmul4bit_v1_recons(grad_output, qweight, scales, zeros, transpose=True)
        else:
            grad = mm4b._matmul4bit_v2_recons(grad_output, qweight, scales, zeros, groupsize=groupsize, transpose=True)
        return grad, None, None, None, None


# Assumes layer is perfectly divisible into 256 * 256 blocks
class Autograd4bitQuantLinear(nn.Module):

    def __init__(self, infeatures, outfeatures, groupsize=-1):
        super().__init__()
        bits = 4
        self.in_features = infeatures
        self.out_features = outfeatures
        self.bits = bits
        self.groupsize = groupsize
        if groupsize == -1:
            self.register_buffer('zeros', torch.empty((outfeatures, 1)))
            self.register_buffer('scales', torch.empty((outfeatures, 1)))
        else:
            self.register_buffer('qzeros',
                                  torch.empty((math.ceil(infeatures/groupsize), outfeatures // 256 * (bits * 8)), dtype=torch.int)
                                )
            self.register_buffer('scales', torch.empty((math.ceil(infeatures/groupsize), outfeatures)))
            self.register_buffer('g_idx', torch.tensor([i // self.groupsize  for i in range(infeatures)], dtype = torch.int32))
        self.bias = nn.Parameter(torch.empty(outfeatures))
        self.register_buffer(
            'qweight', torch.empty((infeatures // 256 * (bits * 8), outfeatures), dtype=torch.int)
        )


    def forward(self, x):
        if torch.is_grad_enabled():
            out = AutogradMatmul4bit.apply(x, self.qweight, self.scales,
                                           self.qzeros if self.groupsize != -1 else self.zeros, self.groupsize)
            out.add_(self.bias)
        else:
            out = mm4b.matmul4bit(x, self.qweight, self.scales,
                                  self.qzeros if self.groupsize != -1 else self.zeros, self.groupsize)
            out.add_(self.bias)
        return out


def make_quant_for_4bit_autograd(module, names, name='', groupsize=-1):
    if isinstance(module, Autograd4bitQuantLinear):
        return
    for attr in dir(module):
        tmp = getattr(module, attr)
        name1 = name + '.' + attr if name != '' else attr
        if name1 in names:
            setattr(
                module, attr, Autograd4bitQuantLinear(tmp.in_features, tmp.out_features, groupsize=groupsize)
            )
    for name1, child in module.named_children():
        make_quant_for_4bit_autograd(child, names, name + '.' + name1 if name != '' else name1, groupsize=groupsize)


def model_to_half(model):
    model.half()
    for n, m in model.named_modules():
        if isinstance(m, Autograd4bitQuantLinear):
            if m.groupsize == -1:
                m.zeros = m.zeros.half()
            m.scales = m.scales.half()
            m.bias = m.bias.half()
    print('Converted as Half.')


def model_to_float(model):
    model.float()
    for n, m in model.named_modules():
        if isinstance(m, Autograd4bitQuantLinear):
            if m.groupsize == -1:
                m.zeros = m.zeros.float()
            m.scales = m.scales.float()
            m.bias = m.bias.float()
    print('Converted as Float.')


def find_layers(module, layers=[nn.Conv2d, nn.Linear], name=''):
    if type(module) in layers:
        return {name: module}
    res = {}
    for name1, child in module.named_children():
        res.update(find_layers(
            child, layers=layers, name=name + '.' + name1 if name != '' else name1
        ))
    return res


def load_llama_model_4bit_low_ram(config_path, model_path, groupsize=-1, half=False, device_map="auto", seqlen=2048):
    import accelerate
    from transformers import LlamaConfig, LlamaForCausalLM, LlamaTokenizer

    print("Loading Model ...")
    t0 = time.time()

    with accelerate.init_empty_weights():
        config = LlamaConfig.from_pretrained(config_path)
        model = LlamaForCausalLM(config)
        model = model.eval()
        layers = find_layers(model)
        for name in ['lm_head']:
            if name in layers:
                del layers[name]
        make_quant_for_4bit_autograd(model, layers, groupsize=groupsize)
    model = accelerate.load_checkpoint_and_dispatch(
        model=model,
        checkpoint=model_path,
        device_map=device_map,
        no_split_module_classes=["LlamaDecoderLayer"]
    )

    model.seqlen = seqlen

    if half:
        model_to_half(model)

    tokenizer = LlamaTokenizer.from_pretrained(config_path)
    tokenizer.truncation_side = 'left'

    print(f"Loaded the model in {(time.time()-t0):.2f} seconds.")

    return model, tokenizer

def load_llama_model_4bit_low_ram_and_offload_to_cpu(config_path, model_path, lora_path=None, groupsize=-1, seqlen=2048, max_memory=None):
    import accelerate
    from transformers import LlamaConfig, LlamaForCausalLM, LlamaTokenizer

    if max_memory is None:
        max_memory = {0: '24Gib', 'cpu': '48Gib'}

    print("Loading Model ...")
    t0 = time.time()

    with accelerate.init_empty_weights():
        config = LlamaConfig.from_pretrained(config_path)
        model = LlamaForCausalLM(config)
        model = model.eval()
        layers = find_layers(model)
        for name in ['lm_head']:
            if name in layers:
                del layers[name]
        make_quant_for_4bit_autograd(model, layers, groupsize=groupsize)
    accelerate.load_checkpoint_in_model(model, checkpoint=model_path, device_map={'': 'cpu'})

    # rotary_emb fix
    for n, m in model.named_modules():
        if 'rotary_emb' in n:
            cos_cached = m.cos_cached.clone().cpu()
            sin_cached = m.sin_cached.clone().cpu()
            break

    if lora_path is not None:
        from peft import PeftModel
        from peft.tuners.lora import Linear4bitLt
        model = PeftModel.from_pretrained(model, lora_path, device_map={'': 'cpu'}, torch_dtype=torch.float32)
        print('{} Lora Applied.'.format(lora_path))

    model.seqlen = seqlen

    print('Apply half ...')
    for n, m in model.named_modules():
        if isinstance(m, Autograd4bitQuantLinear) or ((lora_path is not None) and isinstance(m, Linear4bitLt)):
            if m.groupsize == -1:
                m.zeros = m.zeros.half()
            m.scales = m.scales.half()
            m.bias = m.bias.half()

    print('Dispatching model ...')
    device_map = accelerate.infer_auto_device_map(model, max_memory=max_memory, no_split_module_classes=["LlamaDecoderLayer"])
    model = accelerate.dispatch_model(model, device_map=device_map, offload_buffers=True, main_device=0)
    torch.cuda.empty_cache()
    print('Total {:.2f} Gib VRAM used.'.format(torch.cuda.memory_allocated() / 1024 / 1024))

    # rotary_emb fix
    for n, m in model.named_modules():
        if 'rotary_emb' in n:
            if getattr(m, '_hf_hook', None):
                if isinstance(m._hf_hook, accelerate.hooks.SequentialHook):
                    hooks = m._hf_hook.hooks
                else:
                    hooks = [m._hf_hook]
                for hook in hooks:
                    if hook.offload:
                        if n + '.sin_cached' not in hook.weights_map.dataset.state_dict.keys():
                            hook.weights_map.dataset.state_dict[n + '.sin_cached'] = sin_cached.clone().cpu()
                            hook.weights_map.dataset.state_dict[n + '.cos_cached'] = cos_cached.clone().cpu()

    tokenizer = LlamaTokenizer.from_pretrained(config_path)
    tokenizer.truncation_side = 'left'

    print(f"Loaded the model in {(time.time()-t0):.2f} seconds.")

    return model, tokenizer
