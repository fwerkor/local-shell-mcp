import { useParams, NavLink, Navigate, Link } from 'react-router-dom';
import {
  Activity, Archive, Blocks, FileText, FolderOpen, LayoutDashboard,
  MessagesSquare, Monitor, Server, TerminalSquare, ShieldCheck,
} from 'lucide-react';
import useLocalize from '~/hooks/useLocalize';
import Overview from './Overview';
import Files from './Files';
import Operations from './Operations';
import Desktop from './Desktop';

export const SECTIONS = [
  { id: 'overview', title: 'Overview', titleKey: 'com_lsm_section_overview', descriptionKey: 'com_lsm_section_overview_description', icon: LayoutDashboard, description: 'Controller health and live activity' },
  { id: 'files', title: 'Files', titleKey: 'com_lsm_section_files', descriptionKey: 'com_lsm_section_files_description', icon: FolderOpen, description: 'Local and remote workspaces' },
  { id: 'terminals', title: 'Terminals', titleKey: 'com_lsm_section_terminals', descriptionKey: 'com_lsm_section_terminals_description', icon: TerminalSquare, description: 'Persistent shell sessions' },
  { id: 'desktop', title: 'Desktop', titleKey: 'com_lsm_section_desktop', descriptionKey: 'com_lsm_section_desktop_description', icon: Monitor, description: 'Remote graphical sessions' },
  { id: 'sessions', title: 'Sessions', titleKey: 'com_lsm_section_sessions', descriptionKey: 'com_lsm_section_sessions_description', icon: Blocks, description: 'Logical sessions and lifecycle' },
  { id: 'remotes', title: 'Remotes', titleKey: 'com_lsm_section_remotes', descriptionKey: 'com_lsm_section_remotes_description', icon: Server, description: 'Connected workers' },
  { id: 'audit', title: 'Audit', titleKey: 'com_lsm_section_audit', descriptionKey: 'com_lsm_section_audit_description', icon: ShieldCheck, description: 'Tool activity and inspection' },
] as const;
export type Section = typeof SECTIONS[number]['id'];
export const sectionName = (section: string): string =>
  SECTIONS.find((item) => item.id === section)?.title || 'Controller';

export function ControlSidebar() {
  const localize = useLocalize();
  return (
    <div className="flex h-full flex-col gap-1 overflow-y-auto px-2 py-4">
      <div className="mb-2 flex items-center gap-2 px-2 text-sm font-semibold text-text-primary">
        <img src="/assets/logo.svg" alt="" className="size-7 rounded-lg" />
        local-shell-mcp
      </div>
      <p className="px-2 pb-2 text-xs font-medium uppercase tracking-wider text-text-secondary">{localize('com_lsm_control_plane')}</p>
      {SECTIONS.map(({ id, titleKey, icon: Icon }) => (
        <NavLink key={id} to={'/control/' + id}
          className={({ isActive }) => 'flex items-center gap-3 rounded-lg px-3 py-2 text-sm transition-colors ' +
            (isActive ? 'bg-surface-active-alt font-medium text-text-primary' : 'text-text-secondary hover:bg-surface-hover hover:text-text-primary')}>
          <Icon size={17} />{localize(titleKey)}
        </NavLink>
      ))}
      <div className="my-2 border-t border-border-light" />
      <Link to="/c/new" className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm text-text-secondary hover:bg-surface-hover hover:text-text-primary">
        <MessagesSquare size={17} /> {localize('com_lsm_chat')}
      </Link>
    </div>
  );
}
export default function Control() {
  const localize = useLocalize();
  const { section = 'overview' } = useParams<{ section: string }>();
  const selected = SECTIONS.find((item) => item.id === section);
  if (!selected) return <Navigate to="/control/overview" replace />;
  const Icon = selected.icon;
  return (
    <main className="flex h-full min-h-0 min-w-0 flex-col overflow-y-auto bg-surface-primary text-text-primary">
      <header className="sticky top-0 z-10 border-b border-border-light bg-surface-primary/95 px-5 py-4 backdrop-blur-md sm:px-8">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-3">
          <div className="flex items-center gap-3">
            <span className="rounded-xl border border-border-light bg-surface-secondary p-2"><Icon size={21} /></span>
            <div><h1 className="text-lg font-semibold">{localize(selected.titleKey)}</h1>
              <p className="hidden text-xs text-text-secondary sm:block">{localize(selected.descriptionKey)}</p>
            </div>
          </div>
          <div className="flex items-center gap-2 text-xs text-text-secondary">
            <Activity size={14} /> {localize('com_lsm_controller')}
          </div>
        </div>
      </header>
      <div className="mx-auto w-full max-w-6xl px-4 py-5 sm:px-8">
        <nav aria-label={localize('com_lsm_controller_sections')} className="mb-6 flex gap-1 overflow-x-auto rounded-xl border border-border-light bg-surface-primary-alt p-1">
          {SECTIONS.map(({ id, titleKey }) => (
            <NavLink key={id} to={'/control/' + id}
              className={({ isActive }) => 'shrink-0 rounded-lg px-3 py-2 text-xs font-medium transition-colors sm:text-sm ' +
                (isActive ? 'bg-surface-primary text-text-primary shadow-sm' : 'text-text-secondary hover:bg-surface-hover')}>
              {localize(titleKey)}
            </NavLink>
          ))}
        </nav>
        {section === 'overview' && <Overview />}
        {section === 'files' && <Files />}
        {section === 'desktop' && <Desktop />}
        {['terminals', 'sessions', 'remotes', 'audit'].includes(section) &&
          <Operations key={section} section={section as 'terminals' | 'sessions' | 'remotes' | 'audit'} />}
      </div>
    </main>
  );
}
