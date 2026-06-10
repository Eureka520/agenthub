# 测试报告: PaddleOCR-VL-1.5 vllm 0.20.0 精度测试

## 基本信息
- 目标: 在多款推理硬件上测试 PaddleOCR-VL-1.5 vllm 0.20.0 & vllm 0.21.0 的精度是否可以对齐。
- 提测文档: /nexus/agenthub/ocrvl_vllm_acc.md
- 执行时间: 2026-06-10 06:17:45
- 总状态: PASS
- GPU 设备: 1

## 各阶段详情

### create_vllm_container
- 状态: ok
- 耗时: 30s


- 执行命令:

  - `docker run -d --name harness_vllm_env ...` → ok



### create_paddle_container
- 状态: ok
- 耗时: 5s


- 执行命令:

  - `docker run -d --name harness_paddle_env ...` → ok



### install_vllm_deps
- 状态: ok
- 耗时: 480s


- 执行命令:

  - `pip install transformers>=5.6.0` → ok

  - `pip install vllm==0.20.0` → ok

  - `pip install -U paddleocr[doc-parser]` → ok



### install_paddle_deps
- 状态: ok
- 耗时: 600s


- 执行命令:

  - `pip install paddlepaddle-gpu==3.3.1` → ok

  - `pip install -U paddleocr[doc-parser]` → ok



### download_data
- 状态: ok
- 耗时: 60s


- 执行命令:

  - `wget images.tar (1355 images, reused from /ssd1/images)` → ok



### start_vllm_service
- 状态: ok
- 耗时: 90s


- 执行命令:

  - `vllm serve /ssd1/PaddleOCR-VL-1.5_infer --port 8118 --served-model-name PaddleOCR-VL-1.5-0.9B PaddleOCR-VL-1.6-0.9B` → ok



### run_tf_vllm_test
- 状态: ok
- 耗时: 1800s


- 执行命令:

  - `python run_tf_vllm.py (1355/1355, 0 errors)` → ok



### run_pd_vllm_test
- 状态: ok
- 耗时: 2400s


- 执行命令:

  - `python run_pd_vllm.py (1355/1355, 0 errors)` → ok



### collect_results
- 状态: ok
- 耗时: 30s


- 执行命令:

  - `tar -czf tf_vllm_acc_output.tar.gz (9.0M)` → ok

  - `tar -czf pd_vllm_acc_output.tar.gz (9.0M)` → ok




## GPU/CPU 资源监控
- 监控日志: 未记录(手动执行模式)

- 使用 GPU: 1
- 所有命令通过 CUDA_VISIBLE_DEVICES=1 锁定


## 异常汇总

无异常。


## 环境保留信息

- harness_vllm_env: `docker exec -it harness_vllm_env bash` (GPU: 1)

- harness_paddle_env: `docker exec -it harness_paddle_env bash` (GPU: 1)


## 备选方案选择

- install_vllm_deps: main (cu130, default)
