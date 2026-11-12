import useMedAssistStore from "@/store/medAssistStore";
import { useRibbonDismiss } from "@/hooks/useRibbonDismiss";
import type { TRibbonConfig } from "@/types/ribbon";
import HeaderRibbonView from "./HeaderRibbonView";

/**
 * The header ribbon with its "closed" memory. Lazy-loaded by WidgetContainer,
 * so hosts that don't set `theme.ribbon` never download it.
 */
export default function HeaderRibbon({ config }: { config: TRibbonConfig }) {
  const agentId = useMedAssistStore((s) => s.agentId);
  const text = config.text.trim();
  const dismissable = !!config.dismissable;
  const { dismissed, dismiss } = useRibbonDismiss(
    agentId,
    dismissable ? `ribbon_dismissed:${config.id ?? text}` : null
  );

  if (dismissed) return null;
  return <HeaderRibbonView text={text} icon={config.icon} dismissable={dismissable} onDismiss={dismiss} />;
}
