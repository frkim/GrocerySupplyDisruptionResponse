/**
 * Wire contracts shared with the FastAPI backend (`src/backend/app/contracts.py`).
 * Field names are camelCase because the backend serialises with camelCase keys.
 */

export type HostingMode = 'foundry' | 'local' | 'a2a' | 'system';

export type NodeState =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'awaiting';

export type NodeGroup =
  | 'detection'
  | 'situational'
  | 'impact'
  | 'remediation'
  | 'validation'
  | 'decision'
  | 'execution';

export interface GraphNode {
  id: string;
  label: string;
  description?: string;
  hostingMode: HostingMode;
  group: NodeGroup;
  row: number;
  col: number;
}

export interface GraphEdge {
  from: string;
  to: string;
}

export interface OrchestrationGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface DisruptionSignal {
  productId?: string;
  productName?: string;
  category?: string;
  supplierId?: string;
  confidence?: number;
  depletionDaysMin?: number;
  depletionDaysMax?: number;
  supplyShortfallPct?: number;
  demandSurgePct?: number;
  impactedSkus?: string[];
  affectedRegions?: string[];
  affectedWarehouses?: string[];
  rootCause?: string;
  source?: string;
  detectedAt?: string;
}

export interface AgentInfo {
  nodeId?: string;
  name?: string;
  agentName?: string;
  hostingMode?: HostingMode;
  description?: string;
  model?: string;
  tools?: string[];
}

export interface ToolCall {
  toolName?: string;
  arguments?: string | null;
  result?: string | null;
  durationMs?: number;
}

export interface NodeResult {
  nodeId: string;
  agentName?: string;
  hostingMode?: HostingMode;
  state?: NodeState;
  input?: string;
  narrative?: string;
  structured?: Record<string, unknown>;
  toolCalls?: ToolCall[];
  error?: string | null;
  durationMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

export interface ScenarioScores {
  financial?: number;
  operational?: number;
  customer?: number;
  compliance?: number;
  sustainability?: number;
}

export interface ScenarioOption {
  optionId: string;
  title?: string;
  description?: string;
  leverPrimary?: string;
  costEur?: number;
  timeToImplementDays?: number;
  riskLevel?: string;
  customerImpact?: string;
  shelfAvailabilityRecoveryPct?: number;
  expectedOutcome?: string;
  keyActions?: string[];
  dependencies?: string[];
  scores?: ScenarioScores;
  totalScore?: number;
}

export interface GateRecommendation {
  optionId?: string;
  rationale?: string;
}

export interface RunDecision {
  optionId?: string;
  approver?: string;
  notes?: string;
  decidedAt?: string;
  [key: string]: unknown;
}

export interface RunSummary {
  runId?: string;
  incidentId?: string;
  totalTokens?: number;
  durationMs?: number;
  nodes?: NodeResult[];
  decision?: RunDecision | null;
}

export interface ScenarioResponse {
  signal?: DisruptionSignal;
  graph?: OrchestrationGraph;
  agents?: AgentInfo[];
}

export interface GovernanceAgentRow {
  nodeId?: string;
  agentName?: string;
  name?: string;
  hostingMode?: HostingMode;
  state?: NodeState;
  durationMs?: number;
  promptTokens?: number;
  completionTokens?: number;
  totalTokens?: number;
}

export interface GovernanceResponse {
  agents?: GovernanceAgentRow[];
  totals?: Record<string, unknown>;
}

/* ------------------------------------------------------------------ */
/* Streaming events                                                    */
/* ------------------------------------------------------------------ */

export interface RunStartedEvent {
  type: 'run_started';
  runId?: string;
  incidentId?: string;
  graph?: OrchestrationGraph;
  signal?: DisruptionSignal;
}

export interface NodeStartedEvent {
  type: 'node_started';
  nodeId: string;
  agentName?: string;
  hostingMode?: HostingMode;
}

export interface NodeCompletedEvent {
  type: 'node_completed';
  nodeId: string;
  result?: NodeResult;
}

export interface NodeFailedEvent {
  type: 'node_failed';
  nodeId: string;
  error?: string;
}

export interface NodeSkippedEvent {
  type: 'node_skipped';
  nodeId: string;
  reason?: string;
}

export interface GateAwaitingEvent {
  type: 'gate_awaiting';
  nodeId: string;
  runId?: string;
  options?: ScenarioOption[];
  recommendation?: GateRecommendation;
}

export interface RunCompletedEvent {
  type: 'run_completed';
  summary?: RunSummary;
}

export interface RunFailedEvent {
  type: 'run_failed';
  error?: string;
}

export interface LogStreamEvent {
  type: 'log';
  level?: string;
  message?: string;
}

export interface UnknownEvent {
  type: string;
  [key: string]: unknown;
}

export type StreamEvent =
  | RunStartedEvent
  | NodeStartedEvent
  | NodeCompletedEvent
  | NodeFailedEvent
  | NodeSkippedEvent
  | GateAwaitingEvent
  | RunCompletedEvent
  | RunFailedEvent
  | LogStreamEvent
  | UnknownEvent;

/* ------------------------------------------------------------------ */
/* UI-local models                                                     */
/* ------------------------------------------------------------------ */

export type RunStatus = 'idle' | 'running' | 'awaiting' | 'completed' | 'failed';

export type LogLevel = 'info' | 'warn' | 'error' | 'success' | 'gate';

export interface LogEntry {
  id: number;
  at: number;
  level: LogLevel;
  label: string;
  message: string;
}
