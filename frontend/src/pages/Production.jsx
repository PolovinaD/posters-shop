import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Factory, RefreshCw, RotateCcw, Clock, Loader2, CheckCircle, XCircle } from 'lucide-react';
import { 
  Card, 
  CardHeader, 
  CardTitle, 
  CardContent, 
  Button,
  Loading, 
  ErrorMessage,
  EmptyState,
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  StatusBadge
} from '../components/ui';
import { productionApi } from '../api';

function JobStatusIcon({ status }) {
  switch (status) {
    case 'queued':
      return <Clock className="w-4 h-4 text-amber-400" />;
    case 'processing':
      return <Loader2 className="w-4 h-4 text-purple-400 animate-spin" />;
    case 'completed':
      return <CheckCircle className="w-4 h-4 text-green-400" />;
    case 'failed':
      return <XCircle className="w-4 h-4 text-red-400" />;
    default:
      return null;
  }
}

export default function Production() {
  const queryClient = useQueryClient();
  
  const { data: jobs, isLoading, error, refetch } = useQuery({
    queryKey: ['jobs'],
    queryFn: () => productionApi.getJobs(),
  });
  
  const { data: stats } = useQuery({
    queryKey: ['jobStats'],
    queryFn: productionApi.getJobStats,
  });
  
  const retryMutation = useMutation({
    mutationFn: productionApi.retryJob,
    onSuccess: () => {
      queryClient.invalidateQueries(['jobs']);
      queryClient.invalidateQueries(['jobStats']);
    },
  });
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  const queuedJobs = jobs?.filter(j => j.status === 'queued') || [];
  const processingJobs = jobs?.filter(j => j.status === 'processing') || [];
  const completedJobs = jobs?.filter(j => j.status === 'completed') || [];
  const failedJobs = jobs?.filter(j => j.status === 'failed') || [];
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Production</h1>
          <p className="text-slate-400">Monitor print jobs and production queue</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>
      
      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <Clock className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats?.by_status?.queued || 0}</p>
              <p className="text-sm text-slate-400">Queued</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-purple-500/20 rounded-lg">
              <Loader2 className="w-5 h-5 text-purple-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats?.by_status?.processing || 0}</p>
              <p className="text-sm text-slate-400">Processing</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats?.by_status?.completed || 0}</p>
              <p className="text-sm text-slate-400">Completed</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-slate-700 rounded-lg">
              <Factory className="w-5 h-5 text-slate-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{stats?.avg_processing_time_ms || 0}ms</p>
              <p className="text-sm text-slate-400">Avg Time</p>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Processing Jobs */}
      {processingJobs.length > 0 && (
        <Card className="border-purple-500/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Loader2 className="w-5 h-5 text-purple-400 animate-spin" />
              Currently Processing
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableHead>Job ID</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Started At</TableHead>
                <TableHead>Items</TableHead>
              </TableHeader>
              <TableBody>
                {processingJobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-mono">#{job.id}</TableCell>
                    <TableCell className="font-mono">#{job.order_id}</TableCell>
                    <TableCell className="text-slate-400">
                      {job.started_at ? new Date(job.started_at).toLocaleString() : '-'}
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {job.items_json ? JSON.parse(job.items_json).length : 0} item(s)
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      
      {/* Queued Jobs */}
      {queuedJobs.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Clock className="w-5 h-5 text-amber-400" />
              Queue ({queuedJobs.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableHead>Position</TableHead>
                <TableHead>Job ID</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Items</TableHead>
              </TableHeader>
              <TableBody>
                {queuedJobs.map((job, index) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-mono text-amber-400">#{index + 1}</TableCell>
                    <TableCell className="font-mono">#{job.id}</TableCell>
                    <TableCell className="font-mono">#{job.order_id}</TableCell>
                    <TableCell className="text-slate-400">
                      {new Date(job.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {job.items_json ? JSON.parse(job.items_json).length : 0} item(s)
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      
      {/* Failed Jobs */}
      {failedJobs.length > 0 && (
        <Card className="border-red-500/50">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-400">
              <XCircle className="w-5 h-5" />
              Failed Jobs ({failedJobs.length})
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableHead>Job ID</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Error</TableHead>
                <TableHead>Failed At</TableHead>
                <TableHead></TableHead>
              </TableHeader>
              <TableBody>
                {failedJobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-mono">#{job.id}</TableCell>
                    <TableCell className="font-mono">#{job.order_id}</TableCell>
                    <TableCell className="text-red-400 max-w-xs truncate">
                      {job.error_message || 'Unknown error'}
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {job.completed_at ? new Date(job.completed_at).toLocaleString() : '-'}
                    </TableCell>
                    <TableCell>
                      <Button 
                        size="sm" 
                        variant="warning"
                        onClick={() => retryMutation.mutate(job.id)}
                        loading={retryMutation.isPending}
                      >
                        <RotateCcw className="w-4 h-4" />
                        Retry
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      
      {/* All Jobs History */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Factory className="w-5 h-5" />
            Job History
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {jobs && jobs.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>Job ID</TableHead>
                <TableHead>Order ID</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Processing Time</TableHead>
                <TableHead>Created</TableHead>
              </TableHeader>
              <TableBody>
                {jobs.map((job) => (
                  <TableRow key={job.id}>
                    <TableCell className="font-mono">#{job.id}</TableCell>
                    <TableCell className="font-mono">#{job.order_id}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <JobStatusIcon status={job.status} />
                        <StatusBadge status={job.status} />
                      </div>
                    </TableCell>
                    <TableCell className="font-mono text-slate-400">
                      {job.processing_time_ms ? `${job.processing_time_ms}ms` : '-'}
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {new Date(job.created_at).toLocaleString()}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={Factory}
              title="No production jobs"
              description="Jobs will appear here when orders are paid"
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}

