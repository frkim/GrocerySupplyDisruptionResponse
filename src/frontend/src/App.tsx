import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Header from './components/Header';
import IncidentPanel from './components/IncidentPanel';
import ImpactDashboard from './components/ImpactDashboard';
import AgentGraph from './components/AgentGraph';
import AgentDetailPanel from './components/AgentDetailPanel';
import ScenarioComparison from './components/ScenarioComparison';
import ApprovalGate from './components/ApprovalGate';
import GovernancePanel from './components/GovernancePanel';
import EventLog from './components/EventLog';
import { fetchHealth, fetchScenario, submitDecision } from './api/client';
import { streamRun } from './api/stream';
import { FALLBACK_GRAPH, FALLBACK_SIGNAL } from './lib/fallbackGraph';
import { humanise } from './lib/format';
import type {
  DisruptionSignal,
  GateRecommendation,
  GraphNode,
  LogEntry,
  LogLevel,
  NodeResult,
  NodeState,
  OrchestrationGraph,
  RunDecision,
  RunStatus,
  ScenarioOption,
  StreamEvent,
} from './types';

const MAX_LOG_ENTRIES = 600;

export function App() {
  const [graph, setGraph] = useState<OrchestrationGraph>(FALLBACK_GRAPH);
  const [signal, setSignal] = useState<DisruptionSignal | null>(FALLBACK_SIGNAL);
  const [states, setStates] = useState<Record<string, NodeState>>({});
  const [results, setResults] = useState<Record<string, NodeResult>>({});
  const [logs, setLogs] = useState<LogEntry[]>([]);

  const [status, setStatus] = useState<RunStatus>('idle');
  const [runId, setRunId] = useState<string | null>(null);
  const [incidentId, setIncidentId] = useState<string | null>(null);
  const [backendOnline, setBackendOnline] = useState<boolean | null>(null);

  const [gateOptions, setGateOptions] = useState<ScenarioOption[]>([]);
  const [gateRecommendation, setGateRecommendation] = useState<GateRecommendation | null>(null);
  const [gateOpen, setGateOpen] = useState(false);
  const [selectedOptionId, setSelectedOptionId] = useState<string | null>(null);
  const [decision, setDecision] = useState<RunDecision | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState<string | null>(null);

  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [inspectorOpen, setInspectorOpen] = useState(false);
  const [startedAt, setStartedAt] = useState<number | null>(null);
  const [elapsedMs, setElapsedMs] = useState(0);
  const [finalDurationMs, setFinalDurationMs] = useState<number | null>(null);

  const abortRef = useRef<AbortController | null>(null);
  const logIdRef = useRef(0);
  const manualSelectionRef = useRef(false);

  const appendLog = useCallback((level: LogLevel, label: string, message: string) => {
    logIdRef.current += 1;
    const entry: LogEntry = {
      id: logIdRef.current,
      at: Date.now(),
      level,
      label,
      message,
    };
    setLogs((previous) => {
      const next = [...previous, entry];
      return next.length > MAX_LOG_ENTRIES ? next.slice(next.length - MAX_LOG_ENTRIES) : next;
    });
  }, []);

  /* ---------------- Bootstrap ---------------- */

  useEffect(() => {
    const controller = new AbortController();

    void (async () => {
      try {
        const health = await fetchHealth(controller.signal);
        setBackendOnline(true);
        appendLog('info', 'health', `Backend reachable (${health.status ?? 'ok'}).`);
      } catch {
        if (!controller.signal.aborted) {
          setBackendOnline(false);
          appendLog('warn', 'health', 'Backend unreachable — showing the built-in topology.');
        }
      }

      try {
        const scenario = await fetchScenario(controller.signal);
        if (scenario.graph?.nodes?.length) {
          setGraph({
            nodes: scenario.graph.nodes,
            edges: scenario.graph.edges ?? [],
          });
          appendLog(
            'info',
            'scenario',
            `Topology loaded: ${scenario.graph.nodes.length} agents, ${scenario.graph.edges?.length ?? 0} edges.`,
          );
        }
        if (scenario.signal) setSignal(scenario.signal);
      } catch {
        if (!controller.signal.aborted) {
          appendLog('warn', 'scenario', 'Could not load /api/scenario — using fallback topology.');
        }
      }
    })();

    return () => controller.abort();
  }, [appendLog]);

  /* ---------------- Elapsed timer ---------------- */

  useEffect(() => {
    if (startedAt === null || (status !== 'running' && status !== 'awaiting')) return;
    const timer = window.setInterval(() => setElapsedMs(Date.now() - startedAt), 250);
    return () => window.clearInterval(timer);
  }, [startedAt, status]);

  /* ---------------- Derived ---------------- */

  const nodeById = useMemo(() => {
    const map = new Map<string, GraphNode>();
    for (const node of graph.nodes) map.set(node.id, node);
    return map;
  }, [graph.nodes]);

  const totalTokens = useMemo(
    () =>
      Object.values(results).reduce(
        (sum, result) =>
          sum + (result.totalTokens ?? (result.promptTokens ?? 0) + (result.completionTokens ?? 0)),
        0,
      ),
    [results],
  );

  const completedNodes = useMemo(
    () => Object.values(states).filter((state) => state === 'completed').length,
    [states],
  );

  const scenarioOptions = useMemo<ScenarioOption[]>(() => {
    if (gateOptions.length > 0) return gateOptions;
    return extractOptions(results['scenario_evaluation']?.structured)
      ?? extractOptions(results['response_planner']?.structured)
      ?? [];
  }, [gateOptions, results]);

  const selectedNode = selectedNodeId ? (nodeById.get(selectedNodeId) ?? null) : null;
  const selectedState: NodeState = selectedNodeId
    ? (states[selectedNodeId] ?? 'pending')
    : 'pending';
  const selectedResult = selectedNodeId ? (results[selectedNodeId] ?? null) : null;

  /* ---------------- Event handling ---------------- */

  const applyEvent = useCallback(
    (event: StreamEvent) => {
      switch (event.type) {
        case 'run_started': {
          const started = event as Extract<StreamEvent, { type: 'run_started' }>;
          if (started.runId) setRunId(started.runId);
          if (started.incidentId) setIncidentId(started.incidentId);
          if (started.graph?.nodes?.length) {
            setGraph({ nodes: started.graph.nodes, edges: started.graph.edges ?? [] });
          }
          if (started.signal) setSignal(started.signal);
          appendLog(
            'info',
            'run started',
            `${started.incidentId ?? 'incident'} · ${started.runId ?? 'run'}`,
          );
          break;
        }

        case 'node_started': {
          const started = event as Extract<StreamEvent, { type: 'node_started' }>;
          setStates((prev) => ({ ...prev, [started.nodeId]: 'running' }));
          setResults((prev) => ({
            ...prev,
            [started.nodeId]: {
              ...(prev[started.nodeId] ?? { nodeId: started.nodeId }),
              nodeId: started.nodeId,
              ...(started.agentName ? { agentName: started.agentName } : {}),
              ...(started.hostingMode ? { hostingMode: started.hostingMode } : {}),
              state: 'running',
            },
          }));
          if (!manualSelectionRef.current) {
            setSelectedNodeId(started.nodeId);
            setInspectorOpen(false);
          }
          appendLog(
            'info',
            'started',
            `${started.agentName ?? humanise(started.nodeId)}${started.hostingMode ? ` (${started.hostingMode})` : ''}`,
          );
          break;
        }

        case 'node_completed': {
          const completed = event as Extract<StreamEvent, { type: 'node_completed' }>;
          const result = completed.result;
          setStates((prev) => ({
            ...prev,
            [completed.nodeId]: result?.state ?? 'completed',
          }));
          if (result) {
            setResults((prev) => ({
              ...prev,
              [completed.nodeId]: { ...result, nodeId: completed.nodeId },
            }));
          }
          appendLog(
            'success',
            'completed',
            `${result?.agentName ?? humanise(completed.nodeId)} · ${result?.totalTokens ?? 0} tokens`,
          );
          break;
        }

        case 'node_failed': {
          const failed = event as Extract<StreamEvent, { type: 'node_failed' }>;
          setStates((prev) => ({ ...prev, [failed.nodeId]: 'failed' }));
          setResults((prev) => ({
            ...prev,
            [failed.nodeId]: {
              ...(prev[failed.nodeId] ?? { nodeId: failed.nodeId }),
              nodeId: failed.nodeId,
              state: 'failed',
              error: failed.error ?? 'Unknown error',
            },
          }));
          appendLog('error', 'failed', `${humanise(failed.nodeId)}: ${failed.error ?? 'unknown error'}`);
          break;
        }

        case 'node_skipped': {
          const skipped = event as Extract<StreamEvent, { type: 'node_skipped' }>;
          setStates((prev) => ({ ...prev, [skipped.nodeId]: 'skipped' }));
          appendLog('warn', 'skipped', `${humanise(skipped.nodeId)}: ${skipped.reason ?? 'no reason given'}`);
          break;
        }

        case 'gate_awaiting': {
          const gate = event as Extract<StreamEvent, { type: 'gate_awaiting' }>;
          setStates((prev) => ({ ...prev, [gate.nodeId]: 'awaiting' }));
          setGateOptions(gate.options ?? []);
          setGateRecommendation(gate.recommendation ?? null);
          setGateOpen(true);
          setStatus('awaiting');
          if (gate.runId) setRunId(gate.runId);
          if (gate.recommendation?.optionId) setSelectedOptionId(gate.recommendation.optionId);
          appendLog(
            'gate',
            'approval',
            `Run paused at ${humanise(gate.nodeId)} — ${gate.options?.length ?? 0} options, recommending ${gate.recommendation?.optionId ?? 'n/a'}.`,
          );
          break;
        }

        case 'run_completed': {
          const done = event as Extract<StreamEvent, { type: 'run_completed' }>;
          const summary = done.summary;
          if (summary?.nodes?.length) {
            setResults((prev) => {
              const next = { ...prev };
              for (const node of summary.nodes ?? []) {
                if (node?.nodeId) next[node.nodeId] = { ...next[node.nodeId], ...node };
              }
              return next;
            });
            setStates((prev) => {
              const next = { ...prev };
              for (const node of summary.nodes ?? []) {
                if (node?.nodeId) next[node.nodeId] = node.state ?? next[node.nodeId] ?? 'completed';
              }
              return next;
            });
          }
          if (summary?.decision) setDecision(summary.decision);
          if (typeof summary?.durationMs === 'number') setFinalDurationMs(summary.durationMs);
          if (summary?.runId) setRunId(summary.runId);
          setGateOpen(false);
          setStatus('completed');
          appendLog(
            'success',
            'run completed',
            `${summary?.totalTokens ?? 0} tokens in ${Math.round((summary?.durationMs ?? 0) / 1000)} s.`,
          );
          break;
        }

        case 'run_failed': {
          const failed = event as Extract<StreamEvent, { type: 'run_failed' }>;
          setStatus('failed');
          appendLog('error', 'run failed', failed.error ?? 'The orchestrator reported a failure.');
          break;
        }

        case 'log': {
          const logEvent = event as Extract<StreamEvent, { type: 'log' }>;
          appendLog(
            normaliseLevel(logEvent.level),
            logEvent.level ?? 'log',
            logEvent.message ?? '',
          );
          break;
        }

        default:
          // Unknown event types are recorded, never fatal.
          appendLog('info', String((event as { type?: unknown }).type ?? 'event'), 'Unrecognised event received.');
      }
    },
    [appendLog],
  );

  /* ---------------- Run control ---------------- */

  const handleRun = useCallback(() => {
    if (status === 'running' || status === 'awaiting') return;

    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;

    manualSelectionRef.current = false;
    setStates({});
    setResults({});
    setGateOptions([]);
    setGateRecommendation(null);
    setGateOpen(false);
    setSelectedOptionId(null);
    setDecision(null);
    setDecisionError(null);
    setSelectedNodeId(null);
    setInspectorOpen(false);
    setFinalDurationMs(null);
    setStatus('running');
    const now = Date.now();
    setStartedAt(now);
    setElapsedMs(0);
    appendLog('info', 'stream', 'Opening run stream…');

    void (async () => {
      try {
        for await (const event of streamRun(controller.signal)) {
          applyEvent(event);
        }
        // A closed stream never overrides an open gate; the run is genuinely suspended.
        setStatus((current) => (current === 'running' ? 'completed' : current));
        setFinalDurationMs((current) => current ?? Date.now() - now);
        setElapsedMs(Date.now() - now);
        appendLog('info', 'stream', 'Stream closed.');
      } catch (error) {
        if (controller.signal.aborted) {
          appendLog('warn', 'stream', 'Stream aborted.');
          return;
        }
        setStatus('failed');
        setElapsedMs(Date.now() - now);
        appendLog('error', 'stream', error instanceof Error ? error.message : String(error));
      }
    })();
  }, [appendLog, applyEvent, status]);

  const handleReset = useCallback(() => {
    abortRef.current?.abort();
    abortRef.current = null;
    manualSelectionRef.current = false;
    setStates({});
    setResults({});
    setLogs([]);
    setStatus('idle');
    setRunId(null);
    setIncidentId(null);
    setGateOptions([]);
    setGateRecommendation(null);
    setGateOpen(false);
    setSelectedOptionId(null);
    setDecision(null);
    setDecisionError(null);
    setSelectedNodeId(null);
    setInspectorOpen(false);
    setStartedAt(null);
    setElapsedMs(0);
    setFinalDurationMs(null);
  }, []);

  useEffect(() => () => abortRef.current?.abort(), []);

  useEffect(() => {
    if (!selectedNodeId) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setInspectorOpen(false);
    };
    window.addEventListener('keydown', closeOnEscape);
    return () => window.removeEventListener('keydown', closeOnEscape);
  }, [selectedNodeId]);

  const handleDecision = useCallback(
    (payload: { optionId: string; approver: string; notes: string }) => {
      if (!runId) {
        setDecisionError('No run identifier is available; the gate cannot be resolved.');
        return;
      }
      setSubmitting(true);
      setDecisionError(null);

      void (async () => {
        try {
          await submitDecision(runId, payload);
          setDecision({ ...payload, decidedAt: new Date().toISOString() });
          setGateOpen(false);
          setStatus('running');
          appendLog(
            'gate',
            'approved',
            `Option ${payload.optionId} authorised by ${payload.approver}.`,
          );
        } catch (error) {
          const message = error instanceof Error ? error.message : String(error);
          setDecisionError(message);
          appendLog('error', 'gate', message);
        } finally {
          setSubmitting(false);
        }
      })();
    },
    [appendLog, runId],
  );

  const handleSelectNode = useCallback((nodeId: string) => {
    manualSelectionRef.current = true;
    setSelectedNodeId(nodeId);
    setInspectorOpen(true);
  }, []);

  const showGate = gateOpen || decision !== null;

  return (
    <div className="app">
      <Header
        incidentId={incidentId}
        runId={runId}
        status={status}
        elapsedMs={finalDurationMs ?? elapsedMs}
        totalTokens={totalTokens}
        completedNodes={completedNodes}
        totalNodes={graph.nodes.length}
        backendOnline={backendOnline}
        onRun={handleRun}
        onReset={handleReset}
      />

      <main className="app__main">
        <div className="app__col app__col--left">
          <IncidentPanel signal={signal} />
          <ImpactDashboard results={results} />
        </div>

        <div className="app__col app__col--center">
          <AgentGraph
            graph={graph}
            states={states}
            results={results}
            selectedId={selectedNodeId}
            onSelect={handleSelectNode}
          />

          {showGate ? (
            <ApprovalGate
              runId={runId}
              options={scenarioOptions}
              recommendation={gateRecommendation}
              decision={decision}
              submitting={submitting}
              error={decisionError}
              selectedOptionId={selectedOptionId}
              onSelectOption={setSelectedOptionId}
              onSubmit={handleDecision}
            />
          ) : null}

          <ScenarioComparison
            options={scenarioOptions}
            recommendedId={gateRecommendation?.optionId ?? null}
            selectedId={selectedOptionId}
            onSelect={gateOpen ? setSelectedOptionId : undefined}
          />

        </div>

        <div className="app__col app__col--right">
          <EventLog entries={logs} />
          <GovernancePanel
            nodes={graph.nodes}
            states={states}
            results={results}
            totalDurationMs={finalDurationMs ?? elapsedMs}
          />
        </div>
      </main>
      {selectedNode && inspectorOpen ? (
        <AgentDetailPanel
          node={selectedNode}
          state={selectedState}
          result={selectedResult}
          onClose={() => setInspectorOpen(false)}
        />
      ) : null}
    </div>
  );
}

/** Scenario options may arrive nested under a few plausible keys. */
function extractOptions(structured: Record<string, unknown> | undefined): ScenarioOption[] | null {
  if (!structured) return null;
  const candidateKeys = ['options', 'scenarios', 'scenarioOptions', 'mitigationOptions'];
  for (const key of candidateKeys) {
    const value = structured[key];
    if (Array.isArray(value) && value.length > 0) {
      const options = value.filter(
        (item): item is ScenarioOption =>
          typeof item === 'object' && item !== null && 'optionId' in item,
      );
      if (options.length > 0) return options;
    }
  }
  return null;
}

function normaliseLevel(level: string | undefined): LogLevel {
  switch ((level ?? '').toLowerCase()) {
    case 'error':
    case 'critical':
      return 'error';
    case 'warn':
    case 'warning':
      return 'warn';
    case 'success':
      return 'success';
    default:
      return 'info';
  }
}

export default App;
