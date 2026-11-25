import { Input, Label } from '@librechat/client';
import { Controller, useWatch, useFormContext } from 'react-hook-form';
import type { AgentForm } from '~/common';
import { ResolvedProviderIcon } from '~/components/Endpoints/ResolvedProviderIcon';
import AgentCategorySelector from './AgentCategorySelector';
import { useLocalize, useAgentCapabilities } from '~/hooks';
import { useAgentFileEntries } from './Tools/hooks';
import { useAgentPanelContext } from '~/Providers';
import { useProviderIcon } from '~/hooks/Endpoint';
import { ApprovalModeSelect } from '~/components/Chat/approval/ApprovalModeSetting';
import ToolsSection from './Tools/ToolsSection';
import { cn } from '~/utils';
import Instructions from './Instructions';
import FileContext from './FileContext';
import { Panel } from '~/common';

const fieldClass = 'h-9';

export default function AgentConfig() {
  const localize = useLocalize();
  const methods = useFormContext<AgentForm>();
  const { setActivePanel, endpointsConfig, agentsConfig } = useAgentPanelContext();
  const { contextEnabled } = useAgentCapabilities(agentsConfig?.capabilities);

  const {
    control,
    formState: { errors },
  } = methods;
  const provider = useWatch({ control, name: 'provider' });
  const model = useWatch({ control, name: 'model' });
  const agent_id = useWatch({ control, name: 'id' });
  const { contextFiles } = useAgentFileEntries();

  const providerValue = typeof provider === 'string' ? provider : provider?.value;
  const { provider: providerId, imageURL } = useProviderIcon({
    endpoint: providerValue as string,
    endpointsConfig,
  });

  return (
    <div className="h-auto pt-1">
      {/* Identity fields use the full panel width. */}
      <div className="mb-3 mt-1 flex min-w-0 flex-col gap-2">
        <Controller
          name="name"
          rules={{ required: localize('com_ui_agent_name_is_required') }}
          control={control}
          render={({ field }) => (
            <div className="flex flex-col">
              <Input
                {...field}
                value={field.value ?? ''}
                maxLength={256}
                className={cn(fieldClass, 'font-medium')}
                id="name"
                type="text"
                placeholder={localize('com_agents_name_placeholder')}
                aria-label={localize('com_ui_agent_name')}
                aria-invalid={!!errors.name}
                aria-describedby={errors.name ? 'agent-name-error' : undefined}
              />
              {errors.name && (
                <div
                  id="agent-name-error"
                  className="mt-1 text-xs text-text-destructive"
                  role="alert"
                >
                  {errors.name.message}
                </div>
              )}
            </div>
          )}
        />
        <Controller
          name="description"
          control={control}
          render={({ field }) => (
            <Input
              {...field}
              value={field.value ?? ''}
              maxLength={512}
              className={fieldClass}
              id="description"
              type="text"
              placeholder={localize('com_agents_description_placeholder')}
              aria-label={localize('com_ui_agent_description')}
            />
          )}
        />
      </div>

      {/* MODEL + CATEGORY — balanced 2-column grid */}
      <div className="mb-3 grid grid-cols-2 gap-2">
        <div className="flex min-w-0 flex-col">
          <Label
            className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-text-secondary"
            htmlFor="provider"
          >
            {localize('com_ui_model')} <span className="text-text-destructive">*</span>
          </Label>
          <button
            id="provider"
            type="button"
            onClick={() => setActivePanel(Panel.model)}
            title={model || undefined}
            className={cn(
              'relative flex h-9 w-full min-w-0 items-center overflow-hidden rounded-lg border border-border-light bg-surface-secondary text-sm font-medium text-text-primary transition-colors hover:bg-surface-tertiary focus:outline-none focus-visible:ring-2 focus-visible:ring-ring-primary',
              model != null && model ? 'px-1' : 'px-3',
            )}
          >
            <div className="flex w-full min-w-0 items-center gap-2">
              {providerValue !== undefined && (
                <div className="shadow-stroke relative flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-white text-black dark:bg-white">
                  <ResolvedProviderIcon
                    provider={providerId}
                    imageURL={imageURL}
                    size={16}
                    className="h-2/3 w-2/3"
                  />
                </div>
              )}
              <span className="truncate">
                {model != null && model ? model : localize('com_ui_select_model')}
              </span>
            </div>
          </button>
        </div>
        <div className="flex flex-col">
          <Label
            className="mb-1 block text-[11px] font-medium uppercase tracking-wide text-text-secondary"
            htmlFor="category-selector"
          >
            {localize('com_ui_category')} <span className="text-text-destructive">*</span>
          </Label>
          <AgentCategorySelector className="w-full rounded-lg" />
        </div>
      </div>

      {/* INSTRUCTIONS */}
      <Instructions />

      {/* TOOLS — unified built-ins / tools / actions / mcp / skills */}
      <Controller
        name="approval_mode"
        control={control}
        render={({ field }) => (
          <ApprovalModeSelect value={field.value ?? 'inherit'} inherit onChange={field.onChange} />
        )}
      />
      <ToolsSection agentId={agent_id} />

      {/* FILE CONTEXT — standalone section, separate from the tool library */}
      {contextEnabled && (
        <div className="mb-3">
          <FileContext agent_id={agent_id} files={contextFiles} />
        </div>
      )}
    </div>
  );
}
