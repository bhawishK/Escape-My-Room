# Floor height test

Issue #49 tests whether the phone's back camera can estimate the phone's height above the floor with an AI depth model, so the room view's height could follow the phone instead of staying at 1.5 m. iPhone browsers expose no height sensor: no WebXR, no barometer and no LiDAR depth.

## How it works

1. **Measure height:** opens the back camera, shown small top left so it can be aimed at the floor. It also turns on **Turn with phone**, whose orientation sensor gives gravity's direction, and leaves it on afterwards; select **Stop turning** to stop it.
2. **Model:** each frame is fitted, centered, into a 616 × 1064 canvas turned to the frame's orientation and padded with the model's mean color. [Metric3D v2](https://github.com/YvanYin/Metric3D) ViT-Small (`onnx-community/metric3d-vit-small`, CC0-1.0, pinned revision `ee63b95`, 76 MB fp16) estimates depth and surface normals for every pixel. It runs in a Web Worker with [ONNX Runtime Web](https://onnxruntime.ai/) 1.30.0.
3. **Meters:** Metric3D predicts depth as a camera with a 1000 px focal length would see it, so depth is scaled by the frame's focal length on the canvas over 1000. The focal length is assumed to be 0.75 × the frame's long side, the iPhone 16 main camera's roughly 67° view.
4. **Floor:** pixels whose normals face up (within 20° of the sensor's up) are placed in 3D. The floor is the lowest level surface with real support, not the biggest one, so a desk top is not mistaken for it. A plane is fitted through the floor points, and the camera's height is its distance from that plane. Gravity only has to be roughly right.
5. **Settling:** readings continue until the last three agree within 10 cm, and the height is their median, so one outlier is waited out. It gives up after six readings that keep disagreeing, or eight frames with too little floor. The status line shows each reading, the time per reading and the model's inference time.
6. **Done:** the room view eases to the measured height and keeps it. The back camera is released and the model sits idle, so it no longer uses the CPU or moves the view. **Measure again** repeats it, for example after sitting down; the model is already loaded. **Default height** returns to 1.5 m. **Cancel measuring** stops part way and keeps the previous height.

On 20 October 2026 the model ran on an iPhone on the CPU. Measuring continuously made the view's height keep shifting and slowed the response to walking and turning, so it now measures once per request.

Camera frames stay on the phone. The model downloads once from Hugging Face and is kept in the browser's cache storage. The gaze cursor and floor height never use their cameras at the same time.

## Engines

The worker uses the GPU (WebGPU) when the browser grants an adapter, and otherwise the CPU (WebAssembly, single thread). In headless Edge on Windows the WebGPU path crashed inside ONNX Runtime's own callbacks, even when asked to use the CPU, so:

- a tiny warm-up run checks the GPU before the model is used, and crashes are caught and reported;
- if the GPU fails while loading or later, a fresh worker loads ONNX Runtime's plain WebAssembly build, which has no WebGPU code, and measuring continues.

The status line shows **(GPU)** or **(CPU)**, and the diagnostic report records which ran.

## Results so far

Three NYU Depth V2 photos with measured depth (from Metric3D's demo data), true camera height from a plane fitted to the measured floor:

| Photo | True height | Estimate | Error |
| --- | --- | --- | --- |
| 00000 | 1.483 m | 1.526 m | +2.9 % |
| 00050 | 1.453 m | 1.370 m | −5.7 % |
| 00100 | 1.420 m | 1.462 m | +3.0 % |

These use the iPhone's assumed focal length and gravity without its true 3° roll; with the true values the errors are +3.4 %, −5.3 % and +4.2 %. Before the floor plane was fitted, the 3° gravity error alone made two of the three photos fail.

- **Canvas size:** smaller canvases (308 × 532 and 490 × 840) lost the floor or read 15–22 % low, so only the full canvas is used.
- **Browser:** the full path, from a fake camera playing photo 00000 through the worker and the model, settled on **1.53 m** from three readings in headless Edge on the CPU after the GPU fallback, at 23–33 s per reading on a desktop CPU with one thread, and released the camera.

On the iPhone the model runs on the CPU (user-reported, 20 October 2026). Its speed, and the accuracy at tape-measured heights, are not recorded yet.

**The assumed focal length scales every height one for one.** If iPhone Chrome's camera stream is cropped or stabilized, its field of view, and so its focal length, differs from the 0.75 assumption, and a 5 % focal error is a 5 % height error. The first tape-measured height in the device check separates this from the model's own error; if the ratio is the same at every height, correct the focal length rather than the model.

## Using it on the iPhone

1. Build and start the server as in the [startup guide](diagnostic-startup.md), connect the phone, and keep the room view open.
2. Allow camera and motion access when asked. The first time, the model downloads (76 MB).
3. Select **Measure height** and hold the phone still so the camera sees open floor, with the floor filling at least a third of the picture, until it settles.
4. When readings appear, measure the phone's lens height with a tape measure and compare.
5. Download the diagnostic report: its `floor_height` section keeps the last measurement's readings and height, the engine and the timings.

## Device check

| Field | Result |
| --- | --- |
| Phone, OS, browser version | Pending |
| Engine (GPU or CPU), model load time (`model_load_s`; the first time includes the download) | CPU (user-reported); load time pending |
| Seconds per reading, inference time | Pending |
| Estimate and spread at a tape-measured 0.5 m | Pending |
| Estimate and spread at a tape-measured 1.0 m | Pending |
| Estimate and spread at a tape-measured 1.5 m | Pending |
| Little floor in view; plain and patterned floors; dim light | Pending |
| Camera refusal, stop, page exit | Pending |
| Recommendation: keep for the room view's height, or not | Pending |

## Verified so far

Automated, desktop only:

- Floor height on synthetic depth maps: an open floor, a desk top filling most of the view, too little floor, and gravity 4° off; gravity from the orientation sensor upright, leaning and in landscape; the canvas and placement; float16 encoding; cropping the model output to the frame in meters; and settling on three agreeing readings, waiting out an outlier, or giving up (`frontend/tests/floor-height.spec.ts`).
- A refused camera, a model that cannot download releasing the camera, and the gaze cursor and floor height never running their cameras together (`frontend/tests/connected-view.spec.ts`).
- The NYU and browser runs above were done by hand, because they need the 76 MB model.
