import './style.css';
import { RoomPhotos } from './capture';
import { LiveRoom } from './live-room';
import { RoomPreparation } from './preparation';
import { RoomReconstruction } from './reconstruction';
import { RoomVideo } from './room-video';

const roomPreparation = new RoomPreparation();
const roomPhotos = new RoomPhotos(capture => { void roomPreparation.showCapture(capture); });
void roomPhotos.showLatest().catch(() => undefined);
const liveRoom = new LiveRoom();
void liveRoom.refresh().catch(() => undefined);
void new RoomVideo(new RoomReconstruction(liveRoom)).refresh().catch(() => undefined);
