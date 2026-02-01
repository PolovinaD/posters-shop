import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Package, Plus, Pencil, Trash2, Eye, EyeOff, ImageIcon, RefreshCw, Database } from 'lucide-react';
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
  Input,
  Select
} from '../components/ui';
import { catalogApi, inventoryApi } from '../api';

function ProductModal({ open, onClose, product, categories }) {
  const queryClient = useQueryClient();
  const isEdit = !!product;
  
  const [form, setForm] = useState(product ? {
    sku: product.sku,
    name: product.name,
    description: product.description || '',
    price: product.price,
    category: product.category,
    image_url: product.image_url || '',
    sizes: product.sizes || 'A4,A3,A2',
    active: product.active,
  } : {
    sku: '',
    name: '',
    description: '',
    price: '',
    category: 'Nature',
    image_url: '',
    sizes: 'A4,A3,A2',
    active: true,
  });
  
  const mutation = useMutation({
    mutationFn: (data) => isEdit 
      ? catalogApi.updateProduct(product.sku, data)
      : catalogApi.createProduct(data),
    onSuccess: () => {
      queryClient.invalidateQueries(['catalog-products']);
      onClose();
    },
  });
  
  const handleSubmit = (e) => {
    e.preventDefault();
    const data = {
      ...form,
      price: parseFloat(form.price),
    };
    if (!isEdit) {
      mutation.mutate(data);
    } else {
      // Don't send SKU on update
      const { sku, ...updateData } = data;
      mutation.mutate(updateData);
    }
  };
  
  const categoryOptions = (categories || ['Nature', 'Urban', 'Abstract', 'Minimal'])
    .filter(c => c !== 'All')
    .map(c => ({ value: c, label: c }));
  
  return (
    <Modal open={open} onClose={onClose} title={isEdit ? 'Edit Product' : 'Add Product'}>
      <form onSubmit={handleSubmit} className="space-y-4">
        <Input
          label="SKU"
          value={form.sku}
          onChange={(e) => setForm({ ...form, sku: e.target.value })}
          placeholder="e.g., POSTER-SUNSET-A3"
          required
          disabled={isEdit}
        />
        <Input
          label="Name"
          value={form.name}
          onChange={(e) => setForm({ ...form, name: e.target.value })}
          placeholder="Product name"
          required
        />
        <div>
          <label className="block text-sm font-medium text-slate-300 mb-1">Description</label>
          <textarea
            className="w-full px-4 py-2 bg-slate-800 border border-slate-600 rounded-lg focus:outline-none focus:ring-2 focus:ring-blue-500"
            style={{ color: '#f8fafc' }}
            rows={3}
            value={form.description}
            onChange={(e) => setForm({ ...form, description: e.target.value })}
            placeholder="Product description..."
          />
        </div>
        <div className="grid grid-cols-2 gap-4">
          <Input
            label="Price ($)"
            type="number"
            step="0.01"
            value={form.price}
            onChange={(e) => setForm({ ...form, price: e.target.value })}
            required
          />
          <Select
            label="Category"
            value={form.category}
            onChange={(e) => setForm({ ...form, category: e.target.value })}
            options={categoryOptions}
          />
        </div>
        <Input
          label="Image URL"
          value={form.image_url}
          onChange={(e) => setForm({ ...form, image_url: e.target.value })}
          placeholder="https://..."
        />
        <Input
          label="Sizes (comma-separated)"
          value={form.sizes}
          onChange={(e) => setForm({ ...form, sizes: e.target.value })}
          placeholder="A4,A3,A2"
        />
        <div className="flex items-center gap-2">
          <input
            type="checkbox"
            id="active"
            checked={form.active}
            onChange={(e) => setForm({ ...form, active: e.target.checked })}
            className="rounded"
          />
          <label htmlFor="active" className="text-sm text-slate-300">Active (visible in shop)</label>
        </div>
        
        {mutation.error && (
          <p className="text-red-400 text-sm">{mutation.error.message}</p>
        )}
        
        <div className="flex justify-end gap-3">
          <Button variant="ghost" type="button" onClick={onClose}>
            Cancel
          </Button>
          <Button type="submit" loading={mutation.isPending}>
            {isEdit ? 'Update' : 'Create'} Product
          </Button>
        </div>
      </form>
    </Modal>
  );
}

function SyncInventoryModal({ open, onClose, products }) {
  const queryClient = useQueryClient();
  const [syncing, setSyncing] = useState(false);
  const [results, setResults] = useState(null);
  
  const handleSync = async () => {
    setSyncing(true);
    setResults(null);
    
    const created = [];
    const skipped = [];
    const errors = [];
    
    for (const product of products) {
      try {
        // Try to create stock for this product
        await inventoryApi.createStock({
          sku: product.sku,
          name: product.name,
          available: 100, // Default initial stock
        });
        created.push(product.sku);
      } catch (err) {
        if (err.message.includes('already exists')) {
          skipped.push(product.sku);
        } else {
          errors.push({ sku: product.sku, error: err.message });
        }
      }
    }
    
    setResults({ created, skipped, errors });
    setSyncing(false);
    queryClient.invalidateQueries(['catalog-products']);
    queryClient.invalidateQueries(['stock']);
  };
  
  return (
    <Modal open={open} onClose={onClose} title="Sync to Inventory">
      <div className="space-y-4">
        <p className="text-slate-300">
          This will create inventory stock entries for all catalog products that don't already exist in inventory.
        </p>
        <p className="text-slate-400 text-sm">
          New items will be created with 100 units of initial stock.
        </p>
        
        {results && (
          <div className="space-y-2">
            {results.created.length > 0 && (
              <div className="p-3 bg-green-500/10 rounded-lg text-green-400 text-sm">
                Created: {results.created.join(', ')}
              </div>
            )}
            {results.skipped.length > 0 && (
              <div className="p-3 bg-slate-500/10 rounded-lg text-slate-400 text-sm">
                Already exists: {results.skipped.join(', ')}
              </div>
            )}
            {results.errors.length > 0 && (
              <div className="p-3 bg-red-500/10 rounded-lg text-red-400 text-sm">
                Errors: {results.errors.map(e => `${e.sku}: ${e.error}`).join(', ')}
              </div>
            )}
          </div>
        )}
        
        <div className="flex justify-end gap-3">
          <Button variant="ghost" onClick={onClose}>
            {results ? 'Close' : 'Cancel'}
          </Button>
          {!results && (
            <Button onClick={handleSync} loading={syncing}>
              <Database className="w-4 h-4" />
              Sync Products
            </Button>
          )}
        </div>
      </div>
    </Modal>
  );
}

export default function Catalog() {
  const queryClient = useQueryClient();
  const [productModal, setProductModal] = useState({ open: false, product: null });
  const [syncModalOpen, setSyncModalOpen] = useState(false);
  
  const { data: products, isLoading, error, refetch } = useQuery({
    queryKey: ['catalog-products'],
    queryFn: () => catalogApi.getProducts({ active_only: false }),
  });
  
  const { data: categories } = useQuery({
    queryKey: ['catalog-categories'],
    queryFn: catalogApi.getCategories,
  });
  
  const { data: sizes } = useQuery({
    queryKey: ['catalog-sizes'],
    queryFn: catalogApi.getSizes,
  });
  
  const { data: frames } = useQuery({
    queryKey: ['catalog-frames'],
    queryFn: catalogApi.getFrames,
  });
  
  const seedMutation = useMutation({
    mutationFn: catalogApi.seed,
    onSuccess: () => {
      queryClient.invalidateQueries(['catalog-products']);
      queryClient.invalidateQueries(['catalog-categories']);
      queryClient.invalidateQueries(['catalog-sizes']);
      queryClient.invalidateQueries(['catalog-frames']);
    },
  });
  
  const deleteMutation = useMutation({
    mutationFn: catalogApi.deleteProduct,
    onSuccess: () => {
      queryClient.invalidateQueries(['catalog-products']);
    },
  });
  
  const handleDelete = (product) => {
    if (confirm(`Are you sure you want to deactivate "${product.name}"?`)) {
      deleteMutation.mutate(product.sku);
    }
  };
  
  if (isLoading) return <Loading />;
  if (error) return <ErrorMessage message={error.message} retry={refetch} />;
  
  const activeProducts = products?.filter(p => p.active) || [];
  const inactiveProducts = products?.filter(p => !p.active) || [];
  const inStockCount = products?.filter(p => p.in_stock).length || 0;
  
  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold">Catalog</h1>
          <p className="text-slate-400">Manage products, sizes, and frames</p>
        </div>
        <div className="flex gap-3">
          <Button variant="secondary" onClick={() => refetch()}>
            <RefreshCw className="w-4 h-4" />
            Refresh
          </Button>
          <Button variant="secondary" onClick={() => setSyncModalOpen(true)}>
            <Database className="w-4 h-4" />
            Sync to Inventory
          </Button>
          <Button onClick={() => setProductModal({ open: true, product: null })}>
            <Plus className="w-4 h-4" />
            Add Product
          </Button>
        </div>
      </div>
      
      {/* Summary Stats */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Active Products</p>
            <p className="text-2xl font-bold text-green-400">{activeProducts.length}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">In Stock</p>
            <p className="text-2xl font-bold text-blue-400">{inStockCount}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Sizes</p>
            <p className="text-2xl font-bold">{sizes?.length || 0}</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="py-4">
            <p className="text-sm text-slate-400">Frame Options</p>
            <p className="text-2xl font-bold">{frames?.length || 0}</p>
          </CardContent>
        </Card>
      </div>
      
      {/* Seed Data Button (if no products) */}
      {(!products || products.length === 0) && (
        <Card className="border-blue-500/50">
          <CardContent className="flex items-center justify-between py-4">
            <div>
              <p className="font-medium text-blue-400">No products in catalog</p>
              <p className="text-sm text-slate-400">
                Seed the catalog with sample products to get started
              </p>
            </div>
            <Button onClick={() => seedMutation.mutate()} loading={seedMutation.isPending}>
              <Database className="w-4 h-4" />
              Seed Sample Data
            </Button>
          </CardContent>
        </Card>
      )}
      
      {/* Products Table */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Package className="w-5 h-5" />
            Products
          </CardTitle>
        </CardHeader>
        <CardContent className="p-0">
          {products && products.length > 0 ? (
            <Table>
              <TableHeader>
                <TableHead className="w-16">Image</TableHead>
                <TableHead>SKU</TableHead>
                <TableHead>Name</TableHead>
                <TableHead>Category</TableHead>
                <TableHead className="text-right">Price</TableHead>
                <TableHead className="text-right">Stock</TableHead>
                <TableHead>Status</TableHead>
                <TableHead></TableHead>
              </TableHeader>
              <TableBody>
                {products.map((product) => (
                  <TableRow key={product.sku}>
                    <TableCell>
                      {product.image_url ? (
                        <img 
                          src={product.image_url} 
                          alt={product.name}
                          className="w-12 h-12 object-cover rounded"
                        />
                      ) : (
                        <div className="w-12 h-12 bg-slate-700 rounded flex items-center justify-center">
                          <ImageIcon className="w-6 h-6 text-slate-500" />
                        </div>
                      )}
                    </TableCell>
                    <TableCell className="font-mono text-slate-300 text-xs">{product.sku}</TableCell>
                    <TableCell className="font-medium">{product.name}</TableCell>
                    <TableCell>
                      <span className="px-2 py-1 rounded text-xs bg-slate-700 text-slate-300">
                        {product.category}
                      </span>
                    </TableCell>
                    <TableCell className="text-right font-mono">
                      ${parseFloat(product.price).toFixed(2)}
                    </TableCell>
                    <TableCell className="text-right">
                      <span className={product.in_stock ? 'text-green-400' : 'text-red-400'}>
                        {product.available ?? '—'}
                      </span>
                    </TableCell>
                    <TableCell>
                      {product.active ? (
                        <span className="flex items-center gap-1 text-green-400">
                          <Eye className="w-3 h-3" /> Active
                        </span>
                      ) : (
                        <span className="flex items-center gap-1 text-slate-500">
                          <EyeOff className="w-3 h-3" /> Inactive
                        </span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex justify-end gap-2">
                        <Button 
                          size="sm" 
                          variant="secondary"
                          onClick={() => setProductModal({ open: true, product })}
                        >
                          <Pencil className="w-3 h-3" />
                        </Button>
                        {product.active && (
                          <Button 
                            size="sm" 
                            variant="danger"
                            onClick={() => handleDelete(product)}
                          >
                            <Trash2 className="w-3 h-3" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          ) : (
            <EmptyState
              icon={Package}
              title="No products yet"
              description="Add your first product or seed sample data"
              action={
                <Button onClick={() => setProductModal({ open: true, product: null })}>
                  <Plus className="w-4 h-4" />
                  Add Product
                </Button>
              }
            />
          )}
        </CardContent>
      </Card>
      
      {/* Sizes & Frames */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <Card>
          <CardHeader>
            <CardTitle>Sizes</CardTitle>
          </CardHeader>
          <CardContent>
            {sizes && sizes.length > 0 ? (
              <div className="space-y-2">
                {sizes.map((size) => (
                  <div key={size.id} className="flex justify-between items-center p-2 bg-slate-800 rounded">
                    <span>{size.name}</span>
                    <span className={`font-mono ${parseFloat(size.price_delta) >= 0 ? 'text-green-400' : 'text-red-400'}`}>
                      {parseFloat(size.price_delta) >= 0 ? '+' : ''}{parseFloat(size.price_delta).toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500 text-sm">No sizes configured. Seed the catalog to add default sizes.</p>
            )}
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader>
            <CardTitle>Frame Options</CardTitle>
          </CardHeader>
          <CardContent>
            {frames && frames.length > 0 ? (
              <div className="space-y-2">
                {frames.map((frame) => (
                  <div key={frame.id} className="flex justify-between items-center p-2 bg-slate-800 rounded">
                    <span>{frame.name}</span>
                    <span className="font-mono text-green-400">
                      +${parseFloat(frame.extra_price).toFixed(2)}
                    </span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500 text-sm">No frames configured. Seed the catalog to add default frames.</p>
            )}
          </CardContent>
        </Card>
      </div>
      
      {/* Modals */}
      <ProductModal 
        open={productModal.open}
        onClose={() => setProductModal({ open: false, product: null })}
        product={productModal.product}
        categories={categories}
      />
      <SyncInventoryModal
        open={syncModalOpen}
        onClose={() => setSyncModalOpen(false)}
        products={activeProducts}
      />
    </div>
  );
}

