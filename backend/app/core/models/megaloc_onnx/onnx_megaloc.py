"""OnnxMegaLoc — a torch.nn.Module facade over the MegaLoc ONNX session so it
can be dropped straight into an existing Localizer:

    loc.retrieval_model = OnnxMegaLoc('poc_megaloc_onnx/megaloc_fp16.onnx')

`core.extract_global_features` calls `next(model.parameters()).device`, reads
`model._retrieval_backend` / `model._input_size`, then `model(img_tensor)`.
This facade satisfies all of that: it holds a dummy cuda parameter for device
detection and runs the ONNX graph in forward(). No core files are modified.
"""
import os
import numpy as np
import torch
import torch.nn as nn

# ORT's CUDA EP needs CUDA-12 / cuDNN-9 DLLs. The torch cu124 wheel bundles them
# — put its lib dir on the DLL search path BEFORE importing onnxruntime.
_torch_lib = os.path.join(os.path.dirname(torch.__file__), 'lib')
if os.path.isdir(_torch_lib):
    try:
        os.add_dll_directory(_torch_lib)
    except Exception:
        pass
    os.environ['PATH'] = _torch_lib + os.pathsep + os.environ.get('PATH', '')
import onnxruntime as ort
try:
    ort.preload_dlls()
except Exception:
    pass


class OnnxMegaLoc(nn.Module):
    def __init__(self, onnx_path: str, input_size=(518, 518), device: str = 'cuda'):
        super().__init__()
        # dummy param so `next(model.parameters()).device` reports cuda
        self._dev = nn.Parameter(torch.zeros(1, device=device), requires_grad=False)
        self._retrieval_backend = 'megaloc'
        self._input_size = input_size

        so = ort.SessionOptions()
        so.graph_optimization_level = ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        self.sess = ort.InferenceSession(
            onnx_path, so, providers=['CUDAExecutionProvider', 'CPUExecutionProvider'])
        self.on_cuda = 'CUDAExecutionProvider' in self.sess.get_providers()
        print(f"[OnnxMegaLoc] providers={self.sess.get_providers()} on_cuda={self.on_cuda}")
        if not self.on_cuda:
            print("[OnnxMegaLoc] WARNING: CUDA EP not active — ONNX would run on CPU "
                  "(~476ms, SLOWER than torch-GPU 49ms). Caller should keep torch MegaLoc.")
        self.in_name = self.sess.get_inputs()[0].name
        self.out_name = self.sess.get_outputs()[0].name

    @torch.no_grad()
    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # IO-binding: bind the input torch CUDA tensor's device pointer directly so
        # there is NO torch->cpu->numpy->ORT->cpu round trip (that .cpu() also forces
        # a GPU sync, which was ~12ms of the facade overhead). Keeps everything on GPU.
        if x.is_cuda:
            x = x.contiguous().float()
            io = self.sess.io_binding()
            io.bind_input(self.in_name, 'cuda', 0, np.float32, tuple(x.shape), x.data_ptr())
            io.bind_output(self.out_name, 'cuda', 0)
            self.sess.run_with_iobinding(io)
            out = io.copy_outputs_to_cpu()[0]   # 8448 floats — negligible D2H
            return torch.from_numpy(np.asarray(out)).to(x.device)
        arr = np.ascontiguousarray(x.detach().cpu().numpy().astype(np.float32))
        out = self.sess.run([self.out_name], {self.in_name: arr})[0]
        return torch.from_numpy(np.asarray(out)).to(x.device)
