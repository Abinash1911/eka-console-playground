import { render } from "preact";
import "@widget/index.css";
import App from "@widget/App";

// ?theme={"ribbon":{"text":"Hello"}} sets the widget theme, like the embed's `theme` attribute.
const params = new URLSearchParams(location.search);
const theme = JSON.parse(params.get("theme") || "{}");
// ?display=full shows the full-page mode.
// ?im={"text":"Hello","suggestions":[{"label":"Book"}]} sets the agent greeting.
const initialMessage = JSON.parse(params.get("im") || "null") ?? undefined;
const displayMode = params.get("display") === "full" ? "full" : "widget";

render(
  <App agentId="mock-agent" config={{ title: "Mock Assist", environment: "development", displayMode, theme, initialMessage }} />,
  document.getElementById("root")!
);
