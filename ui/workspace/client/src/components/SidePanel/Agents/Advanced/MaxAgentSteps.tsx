import { useFormContext, Controller } from 'react-hook-form';
import { Input, Label, HoverCard, HoverCardPortal, HoverCardContent } from '@librechat/client';
import type { AgentForm } from '~/common';
import { useLocalize } from '~/hooks';
import { InfoTrigger } from './ui';
import { ESide } from '~/common';

export default function MaxAgentSteps() {
  const localize = useLocalize();
  const { control } = useFormContext<AgentForm>();

  return (
    <HoverCard openDelay={50}>
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center gap-1.5">
          <Label htmlFor="recursion_limit" className="w-auto text-[13px] font-medium">
            {localize('com_ui_agent_recursion_limit')}
          </Label>
          <InfoTrigger />
        </div>
        <Controller
          name="recursion_limit"
          control={control}
          render={({ field }) => (
            <Input
              id="recursion_limit"
              type="number"
              inputMode="numeric"
              min={1}
              step={1}
              value={field.value ?? ''}
              onChange={(e) => {
                const value = e.target.value;
                if (value === '') {
                  field.onChange(null);
                } else if (Number.isSafeInteger(Number(value)) && Number(value) > 0) {
                  field.onChange(Number(value));
                }
              }}
              placeholder={localize('com_ui_unlimited')}
              aria-label={localize('com_ui_agent_recursion_limit')}
              className="h-9 w-full"
            />
          )}
        />
      </div>
      <HoverCardPortal>
        <HoverCardContent side={ESide.Top} className="w-80">
          <p className="text-sm text-text-secondary">
            {localize('com_ui_agent_recursion_limit_info')}
          </p>
        </HoverCardContent>
      </HoverCardPortal>
    </HoverCard>
  );
}
