import './style.css';
import { RoomPhotos } from './capture';
import { RoomPreparation } from './preparation';

const roomPreparation = new RoomPreparation();
const roomPhotos = new RoomPhotos(capture => { void roomPreparation.showCapture(capture); });
void roomPhotos.showLatest().catch(() => undefined);
