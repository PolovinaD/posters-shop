import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { Package, Plus, Pencil, Trash2, Eye, EyeOff, ImageIcon, RefreshCw, Database, Layers } from 'lucide-react';
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
    active: product.active,
  } : {
    sku: '',
    name: '',
    description: '',
    price: '',
    category: 'Nature',
    image_url: '',
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
          placeholder="e.g., POSTER-SUNSET"
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

// A family is not sellable; its variants are. This is where an owner decides
// which formats a motif is sold in and what each one costs.
function VariantsModal({ open, onClose, product, sizes }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({ size: '', price: '' });
  const [error, setError] = useState(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['catalog-products'] });
  const fail = (e) => setError(e?.message || 'Request failed');

  const addVariant = useMutation({
    mutationFn: (data) => catalogApi.createVariant(product.sku, data),
    onSuccess: () => { setDraft({ size: '', price: '' }); setError(null); refresh(); },
    onError: fail,
  });
  const editVariant = useMutation({
    mutationFn: ({ sku, data }) => catalogApi.updateVariant(sku, data),
    onSuccess: () => { setError(null); refresh(); },
    onError: fail,
  });
  const removeVariant = useMutation({
    mutationFn: (sku) => catalogApi.deleteVariant(sku),
    onSuccess: () => { setError(null); refresh(); },
    onError: fail,
  });

  if (!product) return null;

  const variants = product.variants ?? [];
  const taken = new Set(variants.map((v) => v.size));
  const available = (sizes ?? []).filter((s) => !taken.has(s.name));

  return (
    <Modal open={open} onClose={onClose} title={`Formats — ${product.name}`} size="lg">
      <div className="space-y-4">
        <p className="text-sm text-slate-400">
          Each format is a separate SKU with its own price and its own stock.
          The SKU is derived from the family so inventory can find it.
        </p>

        {error && <ErrorMessage message={error} />}

        <div className="space-y-2">
          {variants.length === 0 && (
            <p className="text-slate-500 text-sm">
              No formats yet — this motif cannot be ordered until one is added.
            </p>
          )}
          {variants.map((v) => (
            <div key={v.sku} className="flex items-center gap-2 p-2 bg-slate-800 rounded">
              <span className="w-10 font-semibold">{v.size}</span>
              <span className="flex-1 font-mono text-xs text-slate-500">{v.sku}</span>
              <input
                type="number"
                step="0.01"
                min="0"
                defaultValue={parseFloat(v.price)}
                onBlur={(e) => {
                  const price = parseFloat(e.target.value);
                  if (!Number.isNaN(price) && price !== parseFloat(v.price)) {
                    editVariant.mutate({ sku: v.sku, data: { price } });
                  }
                }}
                className="w-24 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-right"
              />
              <Button
                size="sm"
                variant="secondary"
                onClick={() => editVariant.mutate({ sku: v.sku, data: { active: !v.active } })}
              >
                {v.active ? <Eye className="w-3 h-3" /> : <EyeOff className="w-3 h-3" />}
              </Button>
              <Button size="sm" variant="danger" onClick={() => removeVariant.mutate(v.sku)}>
                <Trash2 className="w-3 h-3" />
              </Button>
            </div>
          ))}
        </div>

        {available.length > 0 ? (
          <div className="flex items-end gap-2 border-t border-slate-800 pt-4">
            <Select
              label="Add format"
              className="flex-1"
              value={draft.size}
              onChange={(e) => setDraft({ ...draft, size: e.target.value })}
              options={[
                { value: '', label: 'Choose…' },
                ...available.map((s) => ({ value: s.name, label: s.name })),
              ]}
            />
            <Input
              label="Price"
              type="number"
              step="0.01"
              min="0"
              className="w-32"
              value={draft.price}
              onChange={(e) => setDraft({ ...draft, price: e.target.value })}
            />
            <Button
              disabled={!draft.size || draft.price === ''}
              loading={addVariant.isPending}
              onClick={() =>
                addVariant.mutate({ size: draft.size, price: parseFloat(draft.price) })
              }
            >
              <Plus className="w-4 h-4" />
            </Button>
          </div>
        ) : (
          <p className="text-slate-500 text-sm border-t border-slate-800 pt-4">
            Every defined format is already priced for this motif.
          </p>
        )}
      </div>
    </Modal>
  );
}


// A frame colour and its per-format prices. The prices differ by format on
// purpose: an A1 frame needs about twice the moulding of an A4.
function FramesModal({ open, onClose, frames, sizes }) {
  const queryClient = useQueryClient();
  const [colour, setColour] = useState({ name: '', sku_prefix: '' });
  const [draft, setDraft] = useState({});
  const [error, setError] = useState(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['catalog-frames'] });
  const fail = (e) => setError(e?.message || 'Request failed');
  const ok = () => { setError(null); refresh(); };

  const addColour = useMutation({
    mutationFn: (data) => catalogApi.createFrame(data),
    onSuccess: () => { setColour({ name: '', sku_prefix: '' }); ok(); },
    onError: fail,
  });
  const removeColour = useMutation({
    mutationFn: (id) => catalogApi.deleteFrame(id, true),
    onSuccess: ok,
    onError: fail,
  });
  const addPrice = useMutation({
    mutationFn: ({ frameId, data }) => catalogApi.createFrameVariant(frameId, data),
    onSuccess: () => { setDraft({}); ok(); },
    onError: fail,
  });
  const editPrice = useMutation({
    mutationFn: ({ sku, data }) => catalogApi.updateFrameVariant(sku, data),
    onSuccess: ok,
    onError: fail,
  });

  return (
    <Modal open={open} onClose={onClose} title="Frames" size="lg">
      <div className="space-y-5">
        {error && <ErrorMessage message={error} />}

        {(frames ?? []).map((frame) => {
          const taken = new Set((frame.variants ?? []).map((v) => v.size));
          const free = (sizes ?? []).filter((s) => !taken.has(s.name));
          const d = draft[frame.id] ?? { size: '', price: '' };
          return (
            <div key={frame.id} className="p-3 bg-slate-800 rounded space-y-2">
              <div className="flex items-center justify-between">
                <div>
                  <span className="font-semibold">{frame.name}</span>
                  <span className="ml-2 font-mono text-xs text-slate-500">
                    {frame.sku_prefix}
                  </span>
                </div>
                <Button size="sm" variant="danger" onClick={() => removeColour.mutate(frame.id)}>
                  <Trash2 className="w-3 h-3" />
                </Button>
              </div>

              <div className="flex flex-wrap gap-2">
                {(frame.variants ?? []).map((v) => (
                  <div key={v.sku} className="flex items-center gap-1">
                    <span className="text-xs text-slate-400 w-7">{v.size}</span>
                    <input
                      type="number"
                      step="0.01"
                      min="0"
                      defaultValue={parseFloat(v.price)}
                      onBlur={(e) => {
                        const price = parseFloat(e.target.value);
                        if (!Number.isNaN(price) && price !== parseFloat(v.price)) {
                          editPrice.mutate({ sku: v.sku, data: { price } });
                        }
                      }}
                      className="w-20 px-2 py-1 bg-slate-900 border border-slate-700 rounded text-right text-sm"
                    />
                  </div>
                ))}
                {(frame.variants ?? []).length === 0 && (
                  <span className="text-slate-500 text-sm">
                    Not priced for any format yet, so it cannot be chosen.
                  </span>
                )}
              </div>

              {free.length > 0 && (
                <div className="flex items-end gap-2">
                  <Select
                    className="w-28"
                    value={d.size}
                    onChange={(e) =>
                      setDraft({ ...draft, [frame.id]: { ...d, size: e.target.value } })
                    }
                    options={[
                      { value: '', label: 'Format' },
                      ...free.map((s) => ({ value: s.name, label: s.name })),
                    ]}
                  />
                  <Input
                    type="number"
                    step="0.01"
                    min="0"
                    placeholder="Price"
                    className="w-28"
                    value={d.price}
                    onChange={(e) =>
                      setDraft({ ...draft, [frame.id]: { ...d, price: e.target.value } })
                    }
                  />
                  <Button
                    size="sm"
                    disabled={!d.size || d.price === ''}
                    onClick={() =>
                      addPrice.mutate({
                        frameId: frame.id,
                        data: { size: d.size, price: parseFloat(d.price) },
                      })
                    }
                  >
                    <Plus className="w-3 h-3" />
                  </Button>
                </div>
              )}
            </div>
          );
        })}

        <div className="flex items-end gap-2 border-t border-slate-800 pt-4">
          <Input
            label="New colour"
            className="flex-1"
            placeholder="Brushed Steel"
            value={colour.name}
            onChange={(e) => setColour({ ...colour, name: e.target.value })}
          />
          <Input
            label="SKU prefix"
            className="flex-1"
            placeholder="FRAME-STEEL"
            value={colour.sku_prefix}
            onChange={(e) => setColour({ ...colour, sku_prefix: e.target.value })}
          />
          <Button
            disabled={!colour.name || !colour.sku_prefix}
            loading={addColour.isPending}
            onClick={() => addColour.mutate(colour)}
          >
            <Plus className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </Modal>
  );
}


// The format vocabulary. A variant may only use a format defined here — that
// check is what stops the catalogue and the warehouse drifting apart again.
function SizesModal({ open, onClose, sizes }) {
  const queryClient = useQueryClient();
  const [draft, setDraft] = useState({ name: '', sort_order: '' });
  const [error, setError] = useState(null);

  const refresh = () => queryClient.invalidateQueries({ queryKey: ['catalog-sizes'] });
  const fail = (e) => setError(e?.message || 'Request failed');

  const addSize = useMutation({
    mutationFn: (data) => catalogApi.createSize(data),
    onSuccess: () => { setDraft({ name: '', sort_order: '' }); setError(null); refresh(); },
    onError: fail,
  });
  const removeSize = useMutation({
    mutationFn: ({ id, force }) => catalogApi.deleteSize(id, force),
    onSuccess: () => { setError(null); refresh(); },
    onError: fail,
  });

  return (
    <Modal open={open} onClose={onClose} title="Formats">
      <div className="space-y-4">
        {error && <ErrorMessage message={error} />}
        <div className="space-y-2">
          {(sizes ?? []).map((s) => (
            <div key={s.id} className="flex items-center gap-2 p-2 bg-slate-800 rounded">
              <span className="flex-1 font-semibold">{s.name}</span>
              <span className="font-mono text-xs text-slate-500">#{s.sort_order}</span>
              <Button
                size="sm"
                variant="danger"
                onClick={() => removeSize.mutate({ id: s.id, force: false })}
              >
                <Trash2 className="w-3 h-3" />
              </Button>
            </div>
          ))}
        </div>
        <div className="flex items-end gap-2 border-t border-slate-800 pt-4">
          <Input
            label="Name"
            className="flex-1"
            placeholder="A0"
            value={draft.name}
            onChange={(e) => setDraft({ ...draft, name: e.target.value })}
          />
          <Input
            label="Order"
            type="number"
            className="w-24"
            value={draft.sort_order}
            onChange={(e) => setDraft({ ...draft, sort_order: e.target.value })}
          />
          <Button
            disabled={!draft.name}
            loading={addSize.isPending}
            onClick={() =>
              addSize.mutate({
                name: draft.name,
                sort_order: parseInt(draft.sort_order || '0', 10),
              })
            }
          >
            <Plus className="w-4 h-4" />
          </Button>
        </div>
      </div>
    </Modal>
  );
}


function SyncInventoryModal({ open, onClose, products, frames }) {
  const queryClient = useQueryClient();
  const [syncing, setSyncing] = useState(false);
  const [results, setResults] = useState(null);
  
  const handleSync = async () => {
    setSyncing(true);
    setResults(null);
    
    const created = [];
    const skipped = [];
    const errors = [];
    
    // Stock is held per sellable unit, not per family: POSTER-SUNSET is never
    // ordered, POSTER-SUNSET-A2 is. Frames are stocked in their own right too.
    const sellable = [
      ...(products ?? []).flatMap((p) =>
        (p.variants ?? [])
          .filter((v) => v.active !== false)
          .map((v) => ({ sku: v.sku, name: `${p.name} (${v.size})` }))
      ),
      ...(frames ?? []).flatMap((f) =>
        (f.variants ?? [])
          .filter((v) => v.active !== false)
          .map((v) => ({ sku: v.sku, name: `${f.name} (${v.size})` }))
      ),
    ];

    for (const item of sellable) {
      try {
        await inventoryApi.createStock({
          sku: item.sku,
          name: item.name,
          available: 100, // Default initial stock
        });
        created.push(item.sku);
      } catch (err) {
        if (err.message.includes('already exists')) {
          skipped.push(item.sku);
        } else {
          errors.push({ sku: item.sku, error: err.message });
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
          Creates inventory stock for every sellable unit that has none — each
          poster format and each frame format, not the product families.
        </p>
        <p className="text-slate-400 text-sm">
          New items start with 100 units. Existing ones are left alone.
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
  const [variantsModal, setVariantsModal] = useState({ open: false, product: null });
  const [framesModalOpen, setFramesModalOpen] = useState(false);
  const [sizesModalOpen, setSizesModalOpen] = useState(false);
  
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
    queryFn: () => catalogApi.getFrames(),
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
                          title="Formats and prices"
                          onClick={() => setVariantsModal({ open: true, product })}
                        >
                          <Layers className="w-3 h-3" />
                        </Button>
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
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Sizes</CardTitle>
            <Button size="sm" variant="secondary" onClick={() => setSizesModalOpen(true)}>
              Manage
            </Button>
          </CardHeader>
          <CardContent>
            {sizes && sizes.length > 0 ? (
              <div className="space-y-2">
                {sizes.map((size) => (
                  <div key={size.id} className="flex justify-between items-center p-2 bg-slate-800 rounded">
                    <span>{size.name}</span>
                    {/* A format no longer carries a price: each variant is
                        priced on its own row. */}
                    <span className="font-mono text-slate-500">#{size.sort_order}</span>
                  </div>
                ))}
              </div>
            ) : (
              <p className="text-slate-500 text-sm">No sizes configured. Seed the catalog to add default sizes.</p>
            )}
          </CardContent>
        </Card>
        
        <Card>
          <CardHeader className="flex flex-row items-center justify-between">
            <CardTitle>Frame Options</CardTitle>
            <Button size="sm" variant="secondary" onClick={() => setFramesModalOpen(true)}>
              Manage
            </Button>
          </CardHeader>
          <CardContent>
            {frames && frames.length > 0 ? (
              <div className="space-y-2">
                {frames.map((frame) => (
                  <div key={frame.id} className="p-2 bg-slate-800 rounded">
                    <div className="flex justify-between items-center">
                      <span>{frame.name}</span>
                      <span className="font-mono text-slate-500 text-xs">{frame.sku_prefix}</span>
                    </div>
                    {/* The price of a frame depends on the format it is made
                        for, so each format is listed with its own price. */}
                    <div className="flex flex-wrap gap-2 mt-1">
                      {(frame.variants ?? []).map((v) => (
                        <span key={v.sku} className="font-mono text-xs text-green-400">
                          {v.size} ${parseFloat(v.price).toFixed(2)}
                        </span>
                      ))}
                    </div>
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
        frames={frames}
      />
      <VariantsModal
        open={variantsModal.open}
        onClose={() => setVariantsModal({ open: false, product: null })}
        product={
          // Re-read from the live list so the modal reflects edits immediately.
          products?.find((p) => p.sku === variantsModal.product?.sku) ??
          variantsModal.product
        }
        sizes={sizes}
      />
      <FramesModal
        open={framesModalOpen}
        onClose={() => setFramesModalOpen(false)}
        frames={frames}
        sizes={sizes}
      />
      <SizesModal
        open={sizesModalOpen}
        onClose={() => setSizesModalOpen(false)}
        sizes={sizes}
      />
    </div>
  );
}

