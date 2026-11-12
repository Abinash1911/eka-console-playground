// Real @synapse/core, but SynapseSDK is the repo's own MockSynapseSDK (src/test/mockSynapse.ts).
// Only added logic: a canned reply when the user sends a message, so the chat feels alive.
export * from "@synapse/core-real";
import { SYNAPSE_REALTIME_EVENTS } from "@synapse/core-real";
import { MockSynapseSDK } from "@widget/test/mockSynapse";
import { makeToolCallProgress } from "@widget/test/fixtures";
import { SYNAPSE_COMPONENTS } from "@synapse/core-real";

let n = 0;
const noop = () => undefined;
const voiceStub = { on: noop, off: noop, connect: async () => {}, disconnect: noop, mute: noop, unmute: noop };
export class SynapseSDK extends MockSynapseSDK {
  get voice() { return voiceStub as never; }
  constructor(config: Record<string, unknown> = {}) {
    super(config);
    (window as unknown as { synapse: SynapseSDK }).synapse = this;
    this.sendMessage = (async () => {
      const id = `bot-${++n}`;
      setTimeout(() => {
        this.emit(SYNAPSE_REALTIME_EVENTS.MESSAGE_CHUNK, { messageId: id, data: { text: "This is a mock reply. " } });
        this.emit(SYNAPSE_REALTIME_EVENTS.MESSAGE_CHUNK, { messageId: id, data: { text: "Pick a symptom:" } });
        this.emit(SYNAPSE_REALTIME_EVENTS.TOOL_CALL, makeToolCallProgress({ messageId: id, component: SYNAPSE_COMPONENTS.PILL }));
        this.emit(SYNAPSE_REALTIME_EVENTS.END_OF_STREAM, {});
      }, 400);
    }) as never;
  }
}
