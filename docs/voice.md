# Voice

Issue #13. The phone user and the headset user talk while they share the room. It is being built in five parts; this page says what works so far.

| Part | Issue | State |
| --- | --- | --- |
| Python passes the call's set-up messages | #169 | Done |
| The two hear each other | #170 | Done on desktop browsers; not yet tried on the iPhone or the Quest |
| Mute, stop, and messages when voice is refused or fails | #171 | Done on desktop browsers |
| Different networks: STUN/TURN settings and the remote check | #172 | Settings and reporting done; **the check on real networks is not yet run** |
| The check on the iPhone and the Quest in VR | #173 | Voice status and mute inside VR done; **the device check is not yet run** |

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
| Voice connected · direct | Audio is flowing straight between the two devices. "relayed" instead means it goes through a TURN server. It also adds "you are muted" or "the headset is muted" when either is |
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

### Inside VR

The headset's page and its buttons are out of sight in VR, so:

- **The line of text in front of the eyes** says each change of the call for two seconds: waiting for the phone, connecting, connected, the phone muted, or failed. Other lines, such as what is being held, come first.
- **"You are muted · press B or Y to unmute"** stays for as long as the headset is muted.
- **B or Y on a controller** mutes and unmutes. With hands only there is no mute inside VR: leave VR and use the page's **Mute** button.
- **Starting and stopping voice** are on the page, so do them before **Enter VR** or after leaving it.

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

Both devices reach the website through the Cloudflare tunnel, but the tunnel carries only the website and the session WebSocket. The audio has to find its own path between the two devices.

- **STUN** tells each device its public address. It relays nothing, and is usually enough on home Wi-Fi and mobile data.
- **TURN** relays the audio through a server. It is needed where a network blocks direct paths, which university networks often do.

### Settings

The servers are set in the server's `.env` (see `.env.example`), and the pages read them from `GET /api/voice/config` each time voice starts. Restart the server after changing them.

| Setting | Default | Meaning |
| --- | --- | --- |
| `ESCAPE_ROOM_VOICE_STUN_URLS` | `stun:stun.l.google.com:19302` | STUN servers, separated by commas. Empty turns STUN off. |
| `ESCAPE_ROOM_VOICE_TURN_URLS` | none | TURN servers, such as `turn:host:3478,turns:host:5349` |
| `ESCAPE_ROOM_VOICE_TURN_USERNAME`, `ESCAPE_ROOM_VOICE_TURN_CREDENTIAL` | none | The TURN login. Both are required with TURN servers. |
| `ESCAPE_ROOM_VOICE_RELAY_ONLY` | `0` | `1` sends all audio through TURN, to prove the relay works |

A wrong setting stops the server at start-up with its reason, for example a TURN server without its login.

**The TURN login reaches the pages**, because each browser logs in to the relay itself. Anyone who can open the site can read it. Use a login made for this prototype, and change it after the contest.

**Privacy:** a STUN server sees each device's IP address and nothing else. A TURN server carries the audio, encrypted between the two browsers, so it cannot listen.

### How a call connected

Once connected, the status line says **direct** or **relayed**. The diagnostic report on each page (and the phone's **Download diagnostic report**) has more, under `voice`:

| Field | Meaning |
| --- | --- |
| `path.local`, `path.remote` | The kind of address each end used: `host` (its own), `srflx` or `prflx` (its public one), `relay` (TURN) |
| `path.relayed` | Whether either end used TURN |
| `ice_servers`, `relay_only` | The servers this page was given, without logins |
| `retries`, `failures` | How often a call needed its one retry, and how often one failed, since the page loaded |

### The remote check: not yet run

Two devices on one Wi-Fi prove nothing about separate networks, so they don't count. For each row: connect both devices, start voice on both, wait up to 30 seconds, and write down the status line and each page's `voice.path`.

| Phone on | Headset on | STUN only: result | With TURN: result | Date |
| --- | --- | --- | --- | --- |
| Mobile data | Home Wi-Fi | | | |
| Mobile data | University Wi-Fi | | | |
| University Wi-Fi | University Wi-Fi | | | |
| University Wi-Fi | Home Wi-Fi | | | |

If a row fails with STUN only ("Voice failed · The two devices found no way to reach each other"):

1. Get a TURN server. The options, none chosen yet:
   - a free tier of a hosted TURN service, which gives a login to paste in;
   - [coturn](https://github.com/coturn/coturn) on a machine with a public address. The GPU desktop sits behind the university network, so it probably cannot be that machine.
2. Put its address and login in `.env` and restart the server.
3. Set `ESCAPE_ROOM_VOICE_RELAY_ONLY=1` once, and check the call connects and says **relayed**. That proves the relay works.
4. Set it back to `0`, so calls that can go direct still do, and repeat the row.

Record here which server was used and what the requirement turned out to be.

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

## The device check: not yet run

Issue #173. On the iPhone 16 in Chrome and the Meta Quest 3, with the room open on both. Write the result beside each line, with the date and the browser versions.

| Check | Result |
| --- | --- |
| The headset starts voice on the page, enters VR on `/quest/`, and both still hear each other | |
| The line in the headset says "Voice connected" on entering, and the call survives leaving VR | |
| B or Y mutes: the headset shows "You are muted · press B or Y to unmute", and the phone shows the headset is muted | |
| The phone walks round the room with the room view open (8th Wall using the back camera) and voice stays up | |
| **iPhone Chrome keeps the microphone running while 8th Wall uses the back camera** | |
| The phone's screen locks and unlocks, and Chrome goes to the background and back: does the call drop, and does it come back? | |
| A few grabs and throws in the headset while talking | |
| Echo and volume with the phone on its loudspeaker, the headset user speaking | |
| **Stop voice** and **Disconnect** on each device end the call, and the microphone indicator goes off | |
| Refusing the microphone on the iPhone shows the reason, and allowing it afterwards works | |

Things that may need a fix once seen on the devices:

- **Microphone and camera together on the iPhone.** iPhone browsers have at times stopped one capture when another starts. If starting voice stops 8th Wall, or the other way round, the order they start in, or asking for both in one request, is the first thing to try.
- **The phone in the background.** iPhone pauses the microphone when Chrome is not in front. The call should come back by itself within about 24 seconds (the one retry); if it does not, **Stop voice** and **Start voice**.
- **Echo.** The browser's echo cancellation is on, but a phone on loudspeaker next to a quiet room is its hardest case. Earphones on the phone are the fallback.

## Not yet checked

Everything so far has run on desktop browsers only.

