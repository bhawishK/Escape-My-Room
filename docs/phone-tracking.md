# Phone tracking decision

Issue 19 sends the phone's physical movement to Python so the Quest can show it. The room objects stay where they are. This decision chooses the only position the phone is allowed to publish.

## What counts as movement

A phone position is the WebXR viewer pose from an immersive AR session, and only when that pose is not emulated. The phone asks for `local-floor` and `local` without requiring either one, then uses the first space the phone grants, preferring `local-floor`. Requiring either space makes this Android phone reject the session. Quest keeps required `local`. The page samples the position at most 20 times a second and sends the existing `pose` message. Python accepts either reference space. The Quest marker shows the accepted position.

`tracked` requires a position. `inactive`, `lost`, and `emulated` require a null position. An emulated pose is not movement. A compass heading, an accelerometer wiggle, or a finger dragging the page is not movement. Those sensors do not give a position in meters.

Ending AR, hiding the page, or losing the pose sends `lost` or `inactive` with no position. The marker stops. A new tracked pose is the recovery. Poses are not saved while the phone is offline.

## The iPhone

The recorded iPhone Chrome report has no WebXR API. This mechanism cannot start there. Connect phone still joins the room. Enter AR cannot produce a position, and the marker stays inactive. That is the expected result on iPhone 16 Chrome. It is not a passed tracking test.

Issue 19's device check needs a phone browser that exposes positional immersive AR: enter AR, see `tracked`, walk forward, right, and up, and compare the position Python accepted with the marker on the Quest. Then end tracking and start it again. A desktop page cannot close that check.

## What this does not add

No second tracking system, no native ARKit app, and no simulated phone position. Turning this position into room coordinates after alignment stays in Issue 3. Showing the person, selecting the box, and moving the box come later.
