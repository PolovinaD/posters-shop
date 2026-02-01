import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Package, Plus, RefreshCw, AlertTriangle } from 'lucide-react';
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
  Modal,
  Input
} from '../components/ui';
import { inventoryApi } from '../api';

function AddStockModal({ open, onClose }) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState({ sku: '', name: '', available: 100 });
  
  const mutation = useMutation({
    mutationFn: inventoryApi.createStock,
    onSuccess: () => {
      queryClient.invalidateQueries(['stock']);
      onClose();
      setForm({ sku: '', name: '', available: 100 });
    },
  });
  
  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate(form);
  };
  
  return (
    <Modal open={open} onClose={onClose} title="Add New Stock">
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="SKU"
          value={form.sku}
          onChange={(e) => setForm({ ...form, sku: e.target.value })}
          placeholder="e.g., POSTER-SUNSET-A3"
          required
        />
        <Input
          label="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="e.g., Sunset Poster A3"
          required
        />
        <Input
          label="Initial Quantity"
          type="number"
          value={form.available}
          onChange={(e) => setForm({ ...form, available: parseInt(e.target.value) || 0 })}
          min={0}
          required
        />
        {mutation.error && (
          <p className="text-red-400 text-sm">{mutation.error.message}</p>
        )}
        <div className="flex justify-end gap-3">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            Add Stock
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function RestockModal({ open, onClose, item }) {
  const queryClient = useQueryClient();
  const [quantity, setQuantity] = useState(50);
  
  const mutation = useMutation({
    mutationFn: (qty) => inventoryApi.restock(item?.sku, qty),
    onSuccess: () => {
      queryClient.invalidateQueries(['stock']);
      onClose();
    },
  });
  
  const handleSubmit = (e) => {
    e.preventDefault();
    mutation.mutate(quantity);
  };
  
  if (!item) return null;
  
  return (
    <Modal open={open} onClose={onClose} title={`Restock: ${item.name}`}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <div className="bg-slate-800 rounded-lg p-4">
          <div className="flex justify-between text-sm">
            <span className="text-slate-400">Current Available</span>
            <span className="font-mono">{item.available}</span>
          </div>
          <div className="flex justify-between text-sm mt-2">
            <span className="text-slate-400">Currently Reserved</span>
            <span className="font-mono">{item.reserved}</span>
          </div>
        </div>
        <Input
          label="Quantity to Add"
          type="number"
          value={quantity}
          onChange={(e) => setQuantity(parseInt(e.target.value) || 0)}
          min={1}
          required
        />
        <div className="flex justify-between items-center p-3 bg-green-500/10 rounded-lg">
          <span className="text-green-400">New Available</span>
          <span className="font-mono text-green-400">{item.available + quantity}</span>
        </div>
        {mutation.error && (
          <p className="text-red-400 text-sm">{mutation.error.message}</p>
        )}
        <div className="flex justify-end gap-3">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" variant="success" loading={mutation.isPending}>
            Restock
          </Button>
        </div>
      </form>
    </Modal>
  );
}

export default function Inventory() {
  const [addModalOpen, setAddModalOpen] = useState(false);
  const [restockItem, setRestockItem] = useState(null);
  
  const { data: stock, isLoading, error, refetch } = useQuery({
    queryKey: ['stock'],
    queryFn: inventoryApi.getStock,
  });
  
  const { data: reservations } = useQuery({
    queryKey: ['reservations'],
    queryFn: inventoryApi.getReservations,
  });
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  const totalAvailable = stock?.reduce((sum, item) => sum + item.available, 0) || 0;
  const totalReserved = stock?.reduce((sum, item) => sum + item.reserved, 0) || 0;
  const lowStockItems = stock?.filter(item => item.available < 10) || [];
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Inventory</h1>
          <p className="text-slate-400">Manage stock levels and reservations</p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
          <Button onClick={() => setAddModalOpen(true)}>
            <Plus className="w-4 h-4" />
            Add Stock
          </Button>
        </div>
      </div>
      
      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Total SKUs</p>
            <p className="text-2xl font-bold">{stock?.length || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Available Stock</p>
            <p className="text-2xl font-bold text-green-400">{totalAvailable}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Reserved Stock</p>
            <p className="text-2xl font-bold text-amber-400">{totalReserved}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Active Reservations</p>
            <p className="text-2xl font-bold">{reservations?.length || 0}</p>
          </CardContent>
        </Card>
      </div>
      
      {/* Low Stock Warning */}
      {lowStockItems.length > 0 && (
        <Card className="border-amber-500/50">
          <CardContent className="flex items-center gap-4 py-4">
            <div className="p-2 bg-amber-500/20 rounded-lg">
              <AlertTriangle className="w-5 h-5 text-amber-400" />
            </div>
            <div>
              <p className="font-medium text-amber-400">Low Stock Warning</p>
              <p className="text-sm text-slate-400">
                {lowStockItems.length} item(s) have less than 10 units available
              </p>
            </div>
          </CardContent>
        </Card>
      )}
      
      {/* Stock Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="w-5 h-5" />
            Stock Levels
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {stock && stock.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead>SKU</TableHead>
                <TableHead>Name</TableHead>
                <TableHead className="text-right">Available</TableHead>
                <TableHead className="text-right">Reserved</TableHead>
                <TableHead className="text-right">Total</TableHead>
                <TableHead></TableHead>
              </TableHeader>
              <TableBody>
                {stock.map((item) => (
                  <TableRow key={item.sku}>
                    <TableCell className="font-mono text-slate-300">{item.sku}</TableCell>
                    <TableCell>{item.name}</TableCell>
                    <TableCell className="text-right">
                      <span className={item.available < 10 ? 'text-red-400' : 'text-green-400'}>
                        {item.available}
                      </span>
                    </TableCell>
                    <TableCell className="text-right text-amber-400">
                      {item.reserved}
                    </TableCell>
                    <TableCell className="text-right text-slate-400">
                      {item.available + item.reserved}
                    </TableCell>
                    <TableCell className="text-right">
                      <Button 
                        size="sm" 
                        variant="secondary"
                        onClick={() => setRestockItem(item)}
                      >
                        Restock
                      </Button>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={Package}
              title="No inventory items"
              description="Add your first stock item to get started"
              action={
                <Button onClick={() => setAddModalOpen(true)}>
                  <Plus className="w-4 h-4" />
                  Add Stock
                </Button>
              }
            />
          )}
        </CardContent>
      </Card>
      
      {/* Active Reservations */}
      {reservations && reservations.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Active Reservations</CardTitle>
          </CardHeader>
          <CardContent className="p-0">
            <Table>
              <TableHeader>
                <TableHead>Order ID</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead>Quantity</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Expires At</TableHead>
              </TableHeader>
              <TableBody>
                {reservations.map((res) => (
                  <TableRow key={res.id}>
                    <TableCell className="font-mono">#{res.order_id}</TableCell>
                    <TableCell className="font-mono text-slate-300">{res.sku}</TableCell>
                    <TableCell>{res.quantity}</TableCell>
                    <TableCell>
                      <span className={`px-2 py-1 rounded text-xs ${
                        res.status === 'pending' ? 'bg-amber-500/20 text-amber-400' :
                        res.status === 'committed' ? 'bg-green-500/20 text-green-400' :
                        'bg-slate-500/20 text-slate-400'
                      }`}>
                        {res.status}
                      </span>
                    </TableCell>
                    <TableCell className="text-slate-400">
                      {res.expires_at ? new Date(res.expires_at).toLocaleString() : '-'}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
      
      <AddStockModal open={addModalOpen} onClose={() => setAddModalOpen(false)} />
      <RestockModal 
        open={!!restockItem} 
        onClose={() => setRestockItem(null)} 
        item={restockItem}
      />
    </div>
  );
}

