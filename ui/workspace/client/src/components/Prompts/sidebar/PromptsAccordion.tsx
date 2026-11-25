import AutoSendPrompt from '../buttons/AutoSendPrompt';
import PromptSidePanel from './GroupSidePanel';
import FilterPrompts from './FilterPrompts';

export default function PromptsAccordion() {
  return (
    <PromptSidePanel className="space-y-2 pt-2">
      <FilterPrompts />
      <AutoSendPrompt />
    </PromptSidePanel>
  );
}
