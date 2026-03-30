import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
  Server,
  Box,
  Activity,
  RefreshCw,
  Play,
  Square,
  Plus,
  Minus,
  Terminal,
  Cpu,
  HardDrive,
  ChevronDown,
  ChevronRight,
  AlertCircle,
  CheckCircle,
  XCircle,
  Zap,
  X
} from 'lucide-react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Button,
  Loading,
  ErrorMessage,
  Modal,
  Input
} from '../components/ui';
import { infraApi } from '../api';

// Status badge component
function StatusBadge({ status }) {
  const config = {
    healthy: { color: 'bg-green-500', icon: CheckCircle, text: 'Healthy' },
    degraded: { color: 'bg-yellow-500', icon: AlertCircle, text: 'Degraded' },
    unhealthy: { color: 'bg-red-500', icon: XCircle, text: 'Unhealthy' },
    Running: { color: 'bg-green-500', icon: CheckCircle, text: 'Running' },
    Pending: { color: 'bg-yellow-500', icon: AlertCircle, text: 'Pending' },
    Failed: { color: 'bg-red-500', icon: XCircle, text: 'Failed' },
  };

  const cfg = config[status] || { color: 'bg-gray-500', icon: Activity, text: status };
  const Icon = cfg.icon;

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium ${cfg.color} text-white`}>
      <Icon className="w-3 h-3" />
      {cfg.text}
    </span>
  );
}

// Resource usage bar
function ResourceBar({ label, value, max, unit }) {
  const percent = max > 0 ? (value / max) * 100 : 0;
  const color = percent > 80 ? 'bg-red-500' : percent > 60 ? 'bg-yellow-500' : 'bg-green-500';

  return (
    <div className="space-y-1">
      <div className="flex justify-between text-xs text-slate-400">
        <span>{label}</span>
        <span>{value?.toFixed(0) || 0}{unit}</span>
      </div>
      <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
        <div className={`h-full ${color} transition-all`} style={{ width: `${Math.min(percent, 100)}%` }} />
      </div>
    </div>
  );
}

// Deployment card
function DeploymentCard({ deployment, onScale, onRestart, onViewPods }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <Card className="border-slate-700">
      <CardContent className="p-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button
              onClick={() => setExpanded(!expanded)}
              className="p-1 hover:bg-slate-700 rounded"
            >
              {expanded ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
            </button>
            <Box className="w-8 h-8 text-blue-400" />
            <div>
              <h3 className="font-semibold text-white">{deployment.name}</h3>
              <p className="text-xs text-slate-400">
                {deployment.available}/{deployment.replicas} replicas
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4">
            <StatusBadge status={deployment.status} />

            <div className="flex items-center gap-1">
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onScale(deployment.name, deployment.replicas - 1)}
                disabled={deployment.replicas <= 0}
              >
                <Minus className="w-4 h-4" />
              </Button>
              <span className="w-8 text-center font-mono">{deployment.replicas}</span>
              <Button
                size="sm"
                variant="ghost"
                onClick={() => onScale(deployment.name, deployment.replicas + 1)}
                disabled={deployment.replicas >= 10}
              >
                <Plus className="w-4 h-4" />
              </Button>
            </div>

            <Button size="sm" variant="secondary" onClick={() => onRestart(deployment.name)}>
              <RefreshCw className="w-4 h-4" />
            </Button>
          </div>
        </div>

        {expanded && (
          <div className="mt-4 pt-4 border-t border-slate-700 grid grid-cols-2 gap-4">
            <ResourceBar
              label="CPU"
              value={deployment.cpu_usage}
              max={300}
              unit="m"
            />
            <ResourceBar
              label="Memory"
              value={deployment.memory_usage}
              max={512}
              unit="MB"
            />
            <div className="col-span-2">
              <p className="text-xs text-slate-500 truncate">
                Image: {deployment.image || 'N/A'}
              </p>
            </div>
            <div className="col-span-2">
              <Button size="sm" variant="ghost" onClick={() => onViewPods(deployment.name)}>
                <Terminal className="w-4 h-4 mr-2" />
                View Pods
              </Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Pods modal
function PodsModal({ open, onClose, deployment, onDeletePod, onViewLogs }) {
  const { data: pods, isLoading } = useQuery({
    queryKey: ['pods', deployment],
    queryFn: () => infraApi.getPods(deployment),
    enabled: open && !!deployment,
    refetchInterval: 5000,
  });

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title={`Pods - ${deployment}`} size="lg">
      {isLoading ? (
        <Loading />
      ) : (
        <div className="space-y-2">
          {pods?.map((pod) => (
            <div key={pod.name} className="flex items-center justify-between p-3 bg-slate-800 rounded-lg">
              <div className="flex items-center gap-3">
                <StatusBadge status={pod.status} />
                <div>
                  <p className="font-mono text-sm text-white">{pod.name}</p>
                  <p className="text-xs text-slate-400">
                    Age: {pod.age} | Restarts: {pod.restarts}
                  </p>
                </div>
              </div>
              <div className="flex gap-2">
                <Button size="sm" variant="ghost" onClick={() => onViewLogs(pod.name)}>
                  <Terminal className="w-4 h-4" />
                </Button>
                <Button size="sm" variant="danger" onClick={() => onDeletePod(pod.name)}>
                  <X className="w-4 h-4" />
                </Button>
              </div>
            </div>
          ))}
          {(!pods || pods.length === 0) && (
            <p className="text-slate-400 text-center py-4">No pods found</p>
          )}
        </div>
      )}
    </Modal>
  );
}

// Logs modal (pod logs via HTTP polling)
function LogsModal({ open, onClose, podName }) {
  const { data, isLoading } = useQuery({
    queryKey: ['logs', podName],
    queryFn: () => infraApi.getPodLogs(podName, 200),
    enabled: open && !!podName,
    refetchInterval: 3000,
  });

  if (!open) return null;

  return (
    <Modal open={open} onClose={onClose} title={`Logs - ${podName}`} size="xl">
      <div className="bg-slate-900 rounded-lg p-4 h-96 overflow-auto font-mono text-xs">
        {isLoading ? (
          <Loading />
        ) : (
          <pre className="text-green-400 whitespace-pre-wrap">{data?.logs || 'No logs available'}</pre>
        )}
      </div>
    </Modal>
  );
}

// HPA card with dynamic metric_type rendering
function HPACard({ hpa, onUpdate }) {
  const [editing, setEditing] = useState(false);
  const [values, setValues] = useState({
    min_replicas: hpa.min_replicas,
    max_replicas: hpa.max_replicas,
    target_cpu: hpa.target_cpu,
  });

  const handleSave = () => {
    onUpdate(hpa.name, values);
    setEditing(false);
  };

  const isRps = hpa.metric_type === 'requests_per_second';
  const currentVal = hpa.current_metric_value ?? hpa.current_cpu;
  const unit = isRps ? ' req/s' : '%';
  const targetLabel = isRps
    ? `target: ${hpa.target_cpu} req/s`
    : `target: ${hpa.target_cpu}%`;
  const metricLabel = isRps ? 'Req/s' : 'CPU';

  // For color coding: compare current vs target
  const ratio = currentVal != null && hpa.target_cpu > 0 ? (currentVal / hpa.target_cpu) * 100 : 0;
  const metricColor = ratio > 100 ? 'text-red-400' : ratio > 80 ? 'text-yellow-400' : 'text-green-400';

  return (
    <Card className="border-slate-700">
      <CardContent className="p-4">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <Zap className="w-6 h-6 text-yellow-400" />
            <div>
              <h3 className="font-semibold text-white">{hpa.name}</h3>
              <p className="text-xs text-slate-400">Horizontal Pod Autoscaler</p>
            </div>
          </div>
          <Button size="sm" variant="secondary" onClick={() => setEditing(!editing)}>
            {editing ? 'Cancel' : 'Edit'}
          </Button>
        </div>

        {editing ? (
          <div className="space-y-3">
            <div className="grid grid-cols-3 gap-3">
              <Input
                label="Min Replicas"
                type="number"
                value={values.min_replicas}
                onChange={(e) => setValues({ ...values, min_replicas: parseInt(e.target.value) })}
              />
              <Input
                label="Max Replicas"
                type="number"
                value={values.max_replicas}
                onChange={(e) => setValues({ ...values, max_replicas: parseInt(e.target.value) })}
              />
              <Input
                label="Target CPU %"
                type="number"
                value={values.target_cpu}
                onChange={(e) => setValues({ ...values, target_cpu: parseInt(e.target.value) })}
              />
            </div>
            <Button onClick={handleSave} className="w-full">Save Changes</Button>
          </div>
        ) : (
          <div className="grid grid-cols-4 gap-4 text-center">
            <div>
              <p className="text-2xl font-bold text-white">{hpa.min_replicas}</p>
              <p className="text-xs text-slate-400">Min</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-blue-400">{hpa.current_replicas}</p>
              <p className="text-xs text-slate-400">Current</p>
            </div>
            <div>
              <p className="text-2xl font-bold text-white">{hpa.max_replicas}</p>
              <p className="text-xs text-slate-400">Max</p>
            </div>
            <div>
              <p className={`text-2xl font-bold ${metricColor}`}>
                {currentVal ?? '—'}{unit}
              </p>
              <p className="text-xs text-slate-400">{metricLabel} ({targetLabel})</p>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// Loki log search panel
const SERVICES = ['users', 'catalog', 'orders', 'production', 'logistics', 'inventory', 'payments', 'infra'];

function LogsPanel() {
  const [service, setService] = useState('orders');
  const [correlationId, setCorrelationId] = useState('');
  const [range, setRange] = useState('1h');
  const [triggered, setTriggered] = useState(false);

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['loki-logs', service, correlationId, range],
    queryFn: () => infraApi.queryLogs(service, correlationId, range),
    enabled: triggered,
    staleTime: 0,
  });

  const handleSearch = () => {
    if (triggered) {
      refetch();
    } else {
      setTriggered(true);
    }
  };

  const lines = data?.lines ?? [];
  const unavailable = data?.loki_unavailable;

  return (
    <div className="space-y-4">
      {/* Search controls */}
      <div className="flex flex-wrap gap-3 items-end">
        <div>
          <label className="block text-xs text-slate-400 mb-1">Service</label>
          <select
            value={service}
            onChange={e => setService(e.target.value)}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded px-3 py-2"
          >
            {SERVICES.map(s => (
              <option key={s} value={s}>{s}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Correlation ID (optional)</label>
          <input
            type="text"
            value={correlationId}
            onChange={e => setCorrelationId(e.target.value)}
            placeholder="e.g. abc-123"
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded px-3 py-2 w-56"
          />
        </div>
        <div>
          <label className="block text-xs text-slate-400 mb-1">Time Range</label>
          <select
            value={range}
            onChange={e => setRange(e.target.value)}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded px-3 py-2"
          >
            <option value="15m">Last 15 min</option>
            <option value="1h">Last 1 hour</option>
            <option value="6h">Last 6 hours</option>
          </select>
        </div>
        <button
          onClick={handleSearch}
          disabled={isLoading}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white text-sm rounded transition-colors disabled:opacity-50"
        >
          {isLoading ? 'Searching...' : 'Search'}
        </button>
      </div>

      {/* Results */}
      {unavailable && (
        <p className="text-amber-400 text-sm">Loki unavailable — log querying requires a running cluster.</p>
      )}
      {triggered && !isLoading && !unavailable && lines.length === 0 && (
        <p className="text-slate-400 text-sm">No log lines found for the selected filters.</p>
      )}
      {lines.length > 0 && (
        <div className="bg-slate-950 rounded p-4 overflow-auto max-h-96 font-mono text-xs text-slate-200 leading-relaxed">
          {lines.map((line, i) => (
            <div key={i} className="whitespace-pre-wrap break-all">{line}</div>
          ))}
        </div>
      )}
    </div>
  );
}

// Main component
export default function Infrastructure() {
  const queryClient = useQueryClient();
  const [activeTab, setActiveTab] = useState('deployments');
  const [selectedDeployment, setSelectedDeployment] = useState(null);
  const [selectedPod, setSelectedPod] = useState(null);

  // Queries
  const { data: cluster, isLoading: clusterLoading } = useQuery({
    queryKey: ['cluster'],
    queryFn: infraApi.getCluster,
    refetchInterval: 10000,
  });

  const { data: deployments, isLoading: deploymentsLoading, error, refetch } = useQuery({
    queryKey: ['deployments'],
    queryFn: infraApi.getDeployments,
    refetchInterval: 5000,
  });

  const { data: hpas } = useQuery({
    queryKey: ['hpas'],
    queryFn: infraApi.getHPAs,
    refetchInterval: 10000,
  });

  // Mutations
  const scaleMutation = useMutation({
    mutationFn: ({ name, replicas }) => infraApi.scaleDeployment(name, replicas),
    onSuccess: () => queryClient.invalidateQueries(['deployments']),
  });

  const restartMutation = useMutation({
    mutationFn: (name) => infraApi.restartDeployment(name),
    onSuccess: () => queryClient.invalidateQueries(['deployments']),
  });

  const deletePodMutation = useMutation({
    mutationFn: (name) => infraApi.deletePod(name),
    onSuccess: () => queryClient.invalidateQueries(['pods']),
  });

  const updateHPAMutation = useMutation({
    mutationFn: ({ name, data }) => infraApi.updateHPA(name, data),
    onSuccess: () => queryClient.invalidateQueries(['hpas']),
  });

  if (deploymentsLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;

  const healthyCount = deployments?.filter(d => d.status === 'healthy').length || 0;
  const totalPods = deployments?.reduce((acc, d) => acc + d.replicas, 0) || 0;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Infrastructure</h1>
          <p className="text-slate-400">
            {cluster?.mode === 'kubernetes' ? 'Connected to Kubernetes cluster' : 'Local development mode'}
          </p>
        </div>
        <Button onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4 mr-2" />
          Refresh
        </Button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <Server className="w-10 h-10 text-blue-400" />
            <div>
              <p className="text-sm text-slate-400">Nodes</p>
              <p className="text-2xl font-bold">{cluster?.node_count || '-'}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <Box className="w-10 h-10 text-green-400" />
            <div>
              <p className="text-sm text-slate-400">Deployments</p>
              <p className="text-2xl font-bold">
                <span className="text-green-400">{healthyCount}</span>
                <span className="text-slate-500">/{deployments?.length || 0}</span>
              </p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <Cpu className="w-10 h-10 text-yellow-400" />
            <div>
              <p className="text-sm text-slate-400">Total Pods</p>
              <p className="text-2xl font-bold">{totalPods}</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <HardDrive className="w-10 h-10 text-purple-400" />
            <div>
              <p className="text-sm text-slate-400">Namespace</p>
              <p className="text-lg font-mono">{cluster?.namespace || 'postershop'}</p>
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Tab switcher */}
      <div className="flex gap-1 border-b border-slate-700 mb-6">
        {[
          { id: 'deployments', label: 'Deployments' },
          { id: 'hpa', label: 'Autoscaling' },
          { id: 'logs', label: 'Logs' },
        ].map(({ id, label }) => (
          <button
            key={id}
            onClick={() => setActiveTab(id)}
            className={`px-4 py-2 text-sm font-medium transition-colors ${
              activeTab === id
                ? 'text-white border-b-2 border-blue-400'
                : 'text-slate-400 hover:text-white'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Deployments tab */}
      {activeTab === 'deployments' && (
        <div>
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Box className="w-5 h-5" />
            Deployments
          </h2>
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {deployments?.map((dep) => (
              <DeploymentCard
                key={dep.name}
                deployment={dep}
                onScale={(name, replicas) => scaleMutation.mutate({ name, replicas })}
                onRestart={(name) => restartMutation.mutate(name)}
                onViewPods={(name) => setSelectedDeployment(name)}
              />
            ))}
          </div>
        </div>
      )}

      {/* Autoscaling tab */}
      {activeTab === 'hpa' && (
        <div>
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Zap className="w-5 h-5" />
            Autoscaling
          </h2>
          {hpas && hpas.length > 0 ? (
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
              {hpas.map((hpa) => (
                <HPACard
                  key={hpa.name}
                  hpa={hpa}
                  onUpdate={(name, data) => updateHPAMutation.mutate({ name, data })}
                />
              ))}
            </div>
          ) : (
            <p className="text-slate-400 text-sm">No HPA resources found.</p>
          )}
        </div>
      )}

      {/* Logs tab */}
      {activeTab === 'logs' && (
        <div>
          <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
            <Terminal className="w-5 h-5" />
            Log Search (Loki)
          </h2>
          <LogsPanel />
        </div>
      )}

      {/* Modals */}
      <PodsModal
        open={!!selectedDeployment}
        onClose={() => setSelectedDeployment(null)}
        deployment={selectedDeployment}
        onDeletePod={(name) => deletePodMutation.mutate(name)}
        onViewLogs={(name) => setSelectedPod(name)}
      />

      <LogsModal
        open={!!selectedPod}
        onClose={() => setSelectedPod(null)}
        podName={selectedPod}
      />
    </div>
  );
}
