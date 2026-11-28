import { useParams } from 'react-router-dom';
import Workspace from './Workspace';

export default function Control() {
  const { section } = useParams<{ section: string }>();
  if (section === 'settings') return null;
  return <Workspace initialSection={section} />;
}
