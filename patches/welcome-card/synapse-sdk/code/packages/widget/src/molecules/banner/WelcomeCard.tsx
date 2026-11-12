import useMedAssistStore from "@/store/medAssistStore";
import { useWelcomeCardDismiss } from "@/hooks/useWelcomeCardDismiss";
import type { TWelcomeCardConfig } from "@/types/welcomeCard";
import WelcomeCardView from "./WelcomeCardView";

/**
 * The welcome card with its "dismissed" memory. Lazy-loaded by ChatWidget, so
 * hosts that don't set `theme.welcomeCard` never download it.
 */
export default function WelcomeCard({ config }: { config: TWelcomeCardConfig }) {
  const agentId = useMedAssistStore((s) => s.agentId);
  const title = config.title.trim();
  const dismissable = !!config.dismissable;
  const { dismissed, dismiss } = useWelcomeCardDismiss(
    agentId,
    dismissable ? `welcome_card_dismissed:${config.id ?? title}` : null
  );

  if (dismissed) return null;
  return (
    <WelcomeCardView
      title={title}
      body={config.body}
      steps={config.steps}
      icon={config.icon}
      dismissable={dismissable}
      dismissLabel={config.dismissLabel}
      onDismiss={dismiss}
    />
  );
}
