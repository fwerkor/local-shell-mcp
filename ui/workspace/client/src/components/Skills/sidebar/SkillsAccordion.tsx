import SkillsSidePanel from './SkillsSidePanel';

export default function SkillsAccordion() {
  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <SkillsSidePanel className="min-h-0 flex-1 border-r-0" />
    </div>
  );
}
