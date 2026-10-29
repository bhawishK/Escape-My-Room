import './style.css';
import { RoomPhotos } from './capture';
import { RoomPreparation } from './preparation';
import { RoomReconstruction } from './reconstruction';
import { RoomVideo } from './room-video';

const roomPreparation = new RoomPreparation();
const roomPhotos = new RoomPhotos(capture => { void roomPreparation.showCapture(capture); });
void roomPhotos.showLatest().catch(() => undefined);
void new RoomVideo(new RoomReconstruction()).refresh().catch(() => undefined);
