import { useQuery } from '@tanstack/react-query';
import { Activity, RefreshCw, CheckCircle, XCircle, Clock, AlertTriangle } from 'lucide-react';
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
} from '../components/ui';
import { ordersApi } from '../api';

function EventStatusIcon({ delivered, retryCount }) {
  if (delivered) {
    return <CheckCircle className="w-4 h-4 text-green-400" />;
  }
  if (retryCount >= 5) {
    return <XCircle className="w-4 h-4 text-red-400" />;
  }
  if (retryCount > 0) {
    return <AlertTriangle className="w-4 h-4 text-amber-400" />;
  }
  return <Clock className="w-4 h-4 text-blue-400" />;
}

export default function Outbox() {
  const { data: outbox, isLoading, error, refetch } = useQuery({
    queryKey: ['outbox'],
    queryFn: ordersApi.getOutboxStats,
  });
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Outbox</h1>
          <p className="text-slate-400">Monitor event delivery with the outbox pattern</p>
        </div>
        <Button variant="secondary" onClick={() => refetch()}>
          <RefreshCw className="w-4 h-4" />
          Refresh
        </Button>
      </div>
      
      {/* Explanation Card */}
      <Card className="bg-gradient-to-r from-blue-500/10 to-purple-500/10 border-blue-500/30">
        <CardContent className="py-4">
          <h3 className="font-semibold text-blue-400 mb-2">🔄 Outbox Pattern</h3>
          <p className="text-sm text-slate-300">
            Events are written to an outbox table in the same transaction as business data. 
            A background worker polls the outbox and delivers events to subscribers. 
            This guarantees <span className="text-green-400 font-medium">at-least-once delivery</span> even 
            if downstream services are temporarily unavailable.
          </p>
        </CardContent>
      </Card>
      
      {/* Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <Clock className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{outbox?.pending_count || 0}</p>
              <p className="text-sm text-slate-400">Pending Events</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-red-500/20 rounded-lg">
              <XCircle className="w-5 h-5 text-red-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">{outbox?.failed_count || 0}</p>
              <p className="text-sm text-slate-400">Failed (Max Retries)</p>
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4 flex items-center gap-4">
            <div className="p-2 bg-green-500/20 rounded-lg">
              <CheckCircle className="w-5 h-5 text-green-400" />
            </div>
            <div>
              <p className="text-2xl font-bold">
                {outbox?.recent_events?.filter(e => e.delivered_at).length || 0}
              </p>
              <p className="text-sm text-slate-400">Recently Delivered</p>
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Events Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Activity className="w-5 h-5" />
            Recent Events
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {outbox?.recent_events && outbox.recent_events.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>Event ID</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Aggregate</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Retries</TableHead>
                <TableHead>Created</TableHead>
                <TableHead>Delivered</TableHead>
              </TableHeader>
              <TableBody>
                {outbox.recent_events.map((event) => (
                  <TableRow key={event.id}>
                    <TableCell className="font-mono">#{event.id}</TableCell>
                    <TableCell>
                      <span className="px-2 py-1 bg-blue-500/20 text-blue-400 rounded text-xs font-mono">
                        {event.event_type}
                      </span>
                    </TableCell>
                    <TableCell className="font-mono text-slate-400">
                      {event.aggregate_id}
                    </TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <EventStatusIcon 
                          delivered={!!event.delivered_at} 
                          retryCount={event.retry_count}
                        />
                        <span className={
                          event.delivered_at ? 'text-green-400' :
                          event.retry_count >= 5 ? 'text-red-400' :
                          event.retry_count > 0 ? 'text-amber-400' :
                          'text-blue-400'
                        }>
                          {event.delivered_at ? 'Delivered' :
                           event.retry_count >= 5 ? 'Failed' :
                           event.retry_count > 0 ? 'Retrying' :
                           'Pending'}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell>
                      {event.retry_count > 0 && (
                        <span className={`font-mono ${
                          event.retry_count >= 5 ? 'text-red-400' :
                          event.retry_count > 2 ? 'text-amber-400' :
                          'text-slate-400'
                        }`}>
                          {event.retry_count}/5
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-slate-400 text-xs">
                      {event.created_at ? new Date(event.created_at).toLocaleString() : '-'}
                    </TableCell>
                    <TableCell className="text-green-400 text-xs">
                      {event.delivered_at ? new Date(event.delivered_at).toLocaleString() : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={Activity}
              title="No events"
              description="Events will appear here when orders are paid or cancelled"
            />
          )}
        </CardContent>
      </Card>
      
      {/* Error Details */}
      {outbox?.recent_events?.some(e => e.last_error) && (
        <Card className="border-red-500/30">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-red-400">
              <AlertTriangle className="w-5 h-5" />
              Delivery Errors
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {outbox.recent_events
                .filter(e => e.last_error)
                .map((event) => (
                  <div key={event.id} className="bg-slate-800 rounded-lg p-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="font-mono text-sm">Event #{event.id}</span>
                      <span className="text-xs text-slate-400">
                        Retry {event.retry_count}/5
                      </span>
                    </div>
                    <p className="text-sm text-red-400 font-mono break-all">
                      {event.last_error}
                    </p>
                  </div>
                ))}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}

