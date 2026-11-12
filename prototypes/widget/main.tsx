import { render } from "preact";
import "@widget/index.css";
import App from "@widget/App";

render(
  <App agentId="mock-agent" config={{ title: "Mock Assist", environment: "development", displayMode: "widget" }} />,
  document.getElementById("root")!
);
