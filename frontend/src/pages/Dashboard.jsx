import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import { 
  Package, 
  ShoppingCart, 
  Factory, 
  Truck, 
  Activity,
  CheckCircle2,
  XCircle,
  Clock,
  Sparkles,
  Layers,
  Loader2
} from 'lucide-react';
import { 
  Card, 
  CardHeader, 
  CardTitle, 
  CardContent, 
  StatCard, 
  Loading, 
  ErrorMessage,
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  StatusBadge,
  HealthIndicator
} from '../components/ui';
import { ordersApi, productionApi, inventoryApi, catalogApi, healthApi } from '../api';

export default function Dashboard() {
  const queryClient = useQueryClient();
  const [seedingCatalog, setSeedingCatalog] = useState(false);
  const [seedingInventory, setSeedingInventory] = useState(false);
  
  const { data: orderStats, isLoading: ordersLoading } = useQuery({
    queryKey: ['orderStats'],
    queryFn: ordersApi.getOrderStats,
  });
  
  const { data: jobStats, isLoading: jobsLoading } = useQuery({
    queryKey: ['jobStats'],
    queryFn: productionApi.getJobStats,
  });
  
  const { data: stock, isLoading: stockLoading } = useQuery({
    queryKey: ['stock'],
    queryFn: inventoryApi.getStock,
  });
  
  const { data: products, isLoading: productsLoading } = useQuery({
    queryKey: ['products'],
    queryFn: catalogApi.getProducts,
  });
  
  const { data: outbox } = useQuery({
    queryKey: ['outbox'],
    queryFn: ordersApi.getOutboxStats,
  });
  
  const { data: health } = useQuery({
    queryKey: ['health'],
    queryFn: healthApi.checkAll,
    refetchInterval: 10000,
  });
  
  const { data: recentOrders } = useQuery({
    queryKey: ['recentOrders'],
    queryFn: () => ordersApi.getOrders({ limit: 5 }),
  });
  
  const handleSeedCatalog = async () => {
    setSeedingCatalog(true);
    try {
      await catalogApi.seed();
      queryClient.invalidateQueries(['products']);
    } catch (e) {
      console.error('Failed to seed catalog:', e);
    } finally {
      setSeedingCatalog(false);
    }
  };
  
  const handleSeedInventory = async () => {
    setSeedingInventory(true);
    try {
      await inventoryApi.seed();
      queryClient.invalidateQueries(['stock']);
    } catch (e) {
      console.error('Failed to seed inventory:', e);
    } finally {
      setSeedingInventory(false);
    }
  };
  
  if (ordersLoading || jobsLoading || stockLoading || productsLoading) {
    return <Loading />;
  }
  
  const catalogEmpty = !products || products.length === 0;
  const inventoryEmpty = !stock || stock.length === 0;
  const needsSetup = catalogEmpty || inventoryEmpty;
  
  // Calculate stats
  const totalOrders = Object.values(orderStats || {}).reduce((a, b) => a + b, 0);
  const activeOrders = (orderStats?.reserved || 0) + (orderStats?.paid || 0) + (orderStats?.producing || 0);
  const totalStock = stock?.reduce((sum, item) => sum + item.available, 0) || 0;
  const reservedStock = stock?.reduce((sum, item) => sum + item.reserved, 0) || 0;
  const queuedJobs = jobStats?.by_status?.queued || 0;
  const processingJobs = jobStats?.by_status?.processing || 0;
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Dashboard</h1>
          <p className="text-slate-400">Overview of your PosterShop platform</p>
        </div>
        <div className="text-sm text-slate-500">
          Auto-refreshes every 5 seconds
        </div>
      </div>
      
      {/* Quick Setup Card - Shows when data needs seeding */}
      {needsSetup && (
        <Card className="border-amber-500/30 bg-amber-500/5">
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-amber-400">
              <Sparkles className="w-5 h-5" />
              Quick Setup
            </CardTitle>
          </CardHeader>
          <CardContent>
            <p className="text-slate-400 mb-4">
              Your platform needs some initial data. Click the buttons below to seed sample data for testing.
            </p>
            <div className="flex flex-wrap gap-3">
              {catalogEmpty && (
                <button
                  onClick={handleSeedCatalog}
                  disabled={seedingCatalog}
                  className="flex items-center gap-2 px-4 py-2 bg-blue-500 hover:bg-blue-600 disabled:bg-blue-500/50 rounded-lg font-medium transition-colors"
                >
                  {seedingCatalog ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Layers className="w-4 h-4" />
                  )}
                  {seedingCatalog ? 'Seeding...' : 'Seed Catalog'}
                </button>
              )}
              {inventoryEmpty && (
                <button
                  onClick={handleSeedInventory}
                  disabled={seedingInventory}
                  className="flex items-center gap-2 px-4 py-2 bg-green-500 hover:bg-green-600 disabled:bg-green-500/50 rounded-lg font-medium transition-colors"
                >
                  {seedingInventory ? (
                    <Loader2 className="w-4 h-4 animate-spin" />
                  ) : (
                    <Package className="w-4 h-4" />
                  )}
                  {seedingInventory ? 'Seeding...' : 'Seed Inventory'}
                </button>
              )}
            </div>
          </CardContent>
        </Card>
      )}
      
      {/* Stats Grid */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-4">
        <StatCard
          title="Total Orders"
          value={totalOrders}
          subtitle={`${activeOrders} active`}
          icon={ShoppingCart}
          color="blue"
        />
        <StatCard
          title="Inventory Items"
          value={totalStock}
          subtitle={`${reservedStock} reserved`}
          icon={Package}
          color="green"
        />
        <StatCard
          title="Production Queue"
          value={queuedJobs + processingJobs}
          subtitle={`${processingJobs} processing`}
          icon={Factory}
          color="purple"
        />
        <StatCard
          title="Outbox Events"
          value={outbox?.pending_count || 0}
          subtitle={`${outbox?.failed_count || 0} failed`}
          icon={Activity}
          color={outbox?.pending_count > 0 ? 'amber' : 'cyan'}
        />
      </div>
      
      {/* Two column layout */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
        {/* Service Health */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <Activity className="w-5 h-5" />
              Service Health
            </CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableHead>Service</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Latency</TableHead>
              </TableHeader>
              <TableBody>
                {health?.map((service) => (
                  <TableRow key={service.name}>
                    <TableCell className="font-medium">{service.name}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <HealthIndicator status={service.status} />
                        <span className={service.status === 'healthy' ? 'text-green-400' : 'text-red-400'}>
                          {service.status}
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {service.latency ? `${service.latency}ms` : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
        
        {/* Order Status Breakdown */}
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <ShoppingCart className="w-5 h-5" />
              Orders by Status
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-3">
              {[
                { status: 'reserved', label: 'Reserved', icon: Clock },
                { status: 'paid', label: 'Paid', icon: CheckCircle2 },
                { status: 'producing', label: 'In Production', icon: Factory },
                { status: 'shipped', label: 'Shipped', icon: Truck },
                { status: 'delivered', label: 'Delivered', icon: CheckCircle2 },
                { status: 'cancelled', label: 'Cancelled', icon: XCircle },
              ].map(({ status, label, icon: Icon }) => (
                <div key={status} className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <Icon className="w-4 h-4 text-slate-400" />
                    <span className="text-slate-300">{label}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-32 h-2 bg-slate-700 rounded-full overflow-hidden">
                      <div 
                        className={`h-full status-${status}`}
                        style={{ 
                          width: `${totalOrders ? ((orderStats?.[status] || 0) / totalOrders) * 100 : 0}%` 
                        }}
                      />
                    </div>
                    <span className="w-8 text-right font-mono">
                      {orderStats?.[status] || 0}
                    </span>
                  </div>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      </div>
      
      {/* Recent Orders */}
      <Card>
        <CardHeader>
          <CardTitle>Recent Orders</CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableHead>Order ID</TableHead>
              <TableHead>Customer</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Total</TableHead>
              <TableHead>Created</TableHead>
            </TableHeader>
            <TableBody>
              {recentOrders?.map((order) => (
                <TableRow key={order.id}>
                  <TableCell className="font-mono">#{order.id}</TableCell>
                  <TableCell>{order.customer_email}</TableCell>
                  <TableCell>
                    <StatusBadge status={order.status} />
                  </TableCell>
                  <TableCell className="font-mono">${order.total_amount}</TableCell>
                  <TableCell className="text-slate-400">
                    {new Date(order.created_at).toLocaleString()}
                  </TableCell>
                </TableRow>
              ))}
              {(!recentOrders || recentOrders.length === 0) && (
                <TableRow>
                  <TableCell colSpan={5} className="text-center text-slate-500 py-8">
                    No orders yet
                  </TableCell>
                </TableRow>
              )}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
}

