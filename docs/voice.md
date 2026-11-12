# Voice

Issue #13. The phone user and the headset user talk while they share the room. It is being built in five parts; this page says what works so far.

| Part | Issue | State |
| --- | --- | --- |
| Python passes the call's set-up messages | #169 | Done |
| The two hear each other | #170 | Done on desktop browsers; not yet tried on the iPhone or the Quest |
| Mute, stop, and messages when voice is refused or fails | #171 | Done on desktop browsers |
| Different networks: STUN/TURN settings and the remote check | #172 | To do |
| The check on the iPhone and the Quest in VR | #173 | To do |

## Using it

1. Connect both devices as usual.
2. On the phone, press **Start voice** in the room view (it is also on the page, under the connect buttons). On the headset's page, `/quest/`, press **Start voice** before **Enter VR**.
3. Allow the microphone when the browser asks.
4. Once both have started, the call connects by itself and each hears the other.

- **Mute** switches this microphone off without ending the call. Both pages show who is muted, and **Unmute** switches it back on. Starting voice again starts unmuted.
- **Stop voice** ends this device's part of the call and lets the microphone go. The other person goes back to waiting.
- **Disconnect**, closing or reloading the page, and a dropped connection all end the call and let the microphone go too.

On the phone, the room view covers the page, so its status line and its **Start voice** and **Mute** buttons are in the room view as well.

The status line, under **Voice** on each page:

| It says | Meaning |
| --- | --- |
| Voice off | Not started, or stopped. A reason follows if the microphone could not be opened. |
| Allow the microphone to talk | The browser is asking |
| Voice on · waiting for the headset to start voice | This device is ready; the other has not started, or is not connected |
| Voice connecting… | Both are ready and the two browsers are finding a path to each other |
| Voice connected | Audio is flowing. It adds "you are muted" or "the headset is muted" when either is |
| Voice failed · … | The two browsers found no path. See [different networks](#different-networks) |

### When something goes wrong

| What happens | What the page says | What to do |
| --- | --- | --- |
| The microphone is refused | Voice off · The microphone was not allowed. Allow it for this site in the browser, then press Start voice again. | Allow it in the browser's site settings and press **Start voice** |
| The device has no microphone | Voice off · No microphone was found on this device. | — |
| Another app holds the microphone | Voice off · The microphone is in use by something else. Close that, then press Start voice again. | Close it and press **Start voice** |
| The page is not on HTTPS | Voice off · Voice needs the trusted HTTPS link. | Open the shared HTTPS address |
| The two browsers find no path, or the call drops and does not come back | Voice connecting…, then Voice failed · The two devices found no way to reach each other. Stop voice and start it again, or try another network. | Both pages say so. **Stop voice**, then **Start voice**; if it keeps failing, see [different networks](#different-networks) |

None of these stops the session: the room, the objects and the other person's presence carry on.

**The one retry.** A call that has not connected after 12 seconds, or that dropped and has not come back in 12, is tried once more over a fresh path (an ICE restart, which the phone starts because it makes the offers). If that also takes 12 seconds, the call has failed. So a failure shows after about 24 seconds, not sooner.

## How it works

- **Audio goes browser to browser.** The two browsers send audio straight to each other with WebRTC. Python never receives, relays or stores any sound.
- **Set-up goes through Python.** To find each other, the browsers swap a few short messages: an offer, an answer, and the network addresses each can be reached on. These go over the session WebSocket as `voice_ready` and `voice_signal`; see [set up a voice call](diagnostic-protocol.md#set-up-a-voice-call).
- **One module for both pages.** `frontend/src/voice.ts` is used unchanged by the phone's page and the headset's page.
- **The phone always makes the offer**, once the shared state shows both are ready, so the two never offer at once.
- **The microphone is asked for inside the tap.** iPhone only asks for the microphone, and only plays the other person, after a tap.
- **Audio settings:** audio only, with the browser's echo cancellation, noise suppression and automatic gain on.

### When someone leaves or reloads

- **The other device reloads or reconnects:** this device goes back to waiting, and sets the call up again when the other is ready. Nothing is pressed here.
- **This device reloads:** pressing **Connect** again also starts voice, if it was on in this tab before. The browser may ask for the microphone again.
- **Disconnect, or a dropped connection:** the call ends and the microphone is let go.
- Each time a device starts voice, Python gives it a new voice session number. A call is tied to the other person's number, so set-up messages left over from an earlier call are ignored.

## Different networks

Not checked yet; that is #172. For now each browser asks one public STUN server, `stun.l.google.com:19302`, for its public address. That is usually enough on home Wi-Fi and mobile data. Some networks, university ones especially, block direct paths, and then the call needs a TURN server to relay the audio. The STUN server sees each device's IP address and nothing else.

## Tests

- `tests/test_voice.py`: Python's side, over the session WebSocket with two connections.
- `frontend/tests/voice.spec.ts`: the phone's page and the headset's page in two browser pages, each with a test tone as its microphone. It checks that:
  - both reach **Voice connected** and each receives the other's audio;
  - the call comes back after the headset reloads, without the phone pressing anything;
  - **Stop voice** ends it for both and **Start voice** brings it back;
  - the room still works during a call, and **Disconnect** ends the call;
  - a mute shows on both pages and switches the microphone off without closing it;
  - **Stop voice** and **Disconnect** each leave no microphone running;
  - a refused microphone says why, leaves the session working, and can be tried again;
  - a call whose browsers never learn each other's addresses is retried once, then both pages say it failed.

The browser test gives each page the microphone permission outright. Only then does Chromium offer every local address, so the test also connects on a machine with a VPN that drops traffic to itself, as the development laptop's does.

## Not yet checked

- On the iPhone and the Quest: #173. In particular, whether iPhone Chrome keeps the microphone running while 8th Wall uses the back camera, and whether the call carries on inside VR.
- Between different networks: #172.
