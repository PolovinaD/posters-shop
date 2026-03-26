import { BrowserRouter, Routes, Route, NavLink, Link, useLocation } from 'react-router-dom';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { 
  LayoutDashboard,
  Layers,
  Package, 
  ShoppingCart, 
  Factory, 
  Truck,
  Activity,
  Users,
  Menu,
  X,
  Store,
  ExternalLink,
  Server
} from 'lucide-react';
import { useState, useEffect } from 'react';

// Admin Pages
import Dashboard from './pages/Dashboard';
import CatalogPage from './pages/Catalog';
import Inventory from './pages/Inventory';
import Orders from './pages/Orders';
import Production from './pages/Production';
import Logistics from './pages/Logistics';
import Outbox from './pages/Outbox';
import UsersPage from './pages/Users';
import Infrastructure from './pages/Infrastructure';

// Shop Pages
import ShopLayout from './pages/shop/ShopLayout';
import Catalog from './pages/shop/Catalog';
import ProductDetail from './pages/shop/ProductDetail';
import Checkout from './pages/shop/Checkout';
import OrderTracking from './pages/shop/OrderTracking';
import Login from './pages/shop/Login';
import Register from './pages/shop/Register';
import MyOrders from './pages/shop/MyOrders';

// Context
import { CartProvider } from './context/CartContext';
import { AuthProvider } from './context/AuthContext';

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchInterval: 5000,
      staleTime: 2000,
    },
  },
});

const navigation = [
  { name: 'Dashboard', href: '/', icon: LayoutDashboard },
  { name: 'Catalog', href: '/catalog', icon: Layers },
  { name: 'Inventory', href: '/inventory', icon: Package },
  { name: 'Orders', href: '/orders', icon: ShoppingCart },
  { name: 'Production', href: '/production', icon: Factory },
  { name: 'Logistics', href: '/logistics', icon: Truck },
  { name: 'Outbox', href: '/outbox', icon: Activity },
  { name: 'Users', href: '/users', icon: Users },
  { name: 'Infrastructure', href: '/infrastructure', icon: Server },
];

function Sidebar({ mobile, onClose }) {
  return (
    <div className={`
      ${mobile ? 'fixed inset-0 z-50 lg:hidden' : 'hidden lg:fixed lg:inset-y-0 lg:flex lg:w-64'}
    `}>
      {mobile && (
        <div className="fixed inset-0 bg-black/50" onClick={onClose} />
      )}
      <div className={`
        relative flex flex-col w-64 bg-[#1e293b] border-r border-[#334155]
        ${mobile ? 'h-full' : 'h-screen'}
      `}>
        <div className="flex items-center justify-between h-16 px-6 border-b border-[#334155]">
          <div className="flex items-center gap-3">
            <div className="w-8 h-8 rounded-lg bg-blue-500 flex items-center justify-center">
              <Package className="w-5 h-5 text-white" />
            </div>
            <span className="text-lg font-semibold">PosterShop</span>
          </div>
          {mobile && (
            <button onClick={onClose} className="lg:hidden">
              <X className="w-6 h-6" />
            </button>
          )}
        </div>
        
        <nav className="flex-1 px-3 py-4 space-y-1">
          {navigation.map((item) => (
            <NavLink
              key={item.name}
              to={item.href}
              onClick={mobile ? onClose : undefined}
              className={({ isActive }) => `
                flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium
                transition-colors duration-150
                ${isActive 
                  ? 'bg-blue-500/20 text-blue-400' 
                  : 'text-slate-400 hover:bg-slate-700/50 hover:text-slate-200'
                }
              `}
            >
              <item.icon className="w-5 h-5" />
              {item.name}
            </NavLink>
          ))}
          
          {/* Shop link */}
          <div className="pt-4 mt-4 border-t border-slate-700">
            <Link
              to="/shop"
              onClick={mobile ? onClose : undefined}
              className="flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm font-medium text-orange-400 hover:bg-orange-500/10 transition-colors"
            >
              <Store className="w-5 h-5" />
              Visit Shop
              <ExternalLink className="w-3 h-3 ml-auto" />
            </Link>
          </div>
        </nav>
        
        <div className="p-4 border-t border-[#334155]">
          <div className="px-3 py-2 rounded-lg bg-slate-800/50">
            <p className="text-xs text-slate-500">Environment</p>
            <p className="text-sm font-medium text-slate-300">Development</p>
          </div>
        </div>
      </div>
    </div>
  );
}

function AdminLayout({ children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const location = useLocation();
  
  // Update page title for admin pages
  useEffect(() => {
    const titles = {
      '/': 'Dashboard - PosterShop Admin',
      '/catalog': 'Catalog - PosterShop Admin',
      '/inventory': 'Inventory - PosterShop Admin',
      '/orders': 'Orders - PosterShop Admin',
      '/production': 'Production - PosterShop Admin',
      '/logistics': 'Logistics - PosterShop Admin',
      '/outbox': 'Outbox - PosterShop Admin',
      '/users': 'Users - PosterShop Admin',
    };
    document.title = titles[location.pathname] || 'PosterShop Admin';
  }, [location.pathname]);
  
  return (
    <div className="min-h-screen bg-[#0f172a] text-white">
      <Sidebar />
      {sidebarOpen && <Sidebar mobile onClose={() => setSidebarOpen(false)} />}
      
      {/* Mobile header */}
      <div className="lg:hidden flex items-center h-16 px-4 bg-[#1e293b] border-b border-[#334155]">
        <button onClick={() => setSidebarOpen(true)}>
          <Menu className="w-6 h-6" />
        </button>
        <span className="ml-4 text-lg font-semibold">PosterShop Admin</span>
      </div>
      
      {/* Main content */}
      <div className="lg:pl-64">
        <main className="p-6 lg:p-8">
          {children}
        </main>
      </div>
    </div>
  );
}

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>
        <CartProvider>
          <BrowserRouter>
            <Routes>
              {/* Shop Routes (light theme) */}
              <Route path="/shop" element={<ShopLayout />}>
                <Route index element={<Catalog />} />
                <Route path="product/:sku" element={<ProductDetail />} />
                <Route path="checkout" element={<Checkout />} />
                <Route path="orders" element={<OrderTracking />} />
                <Route path="orders/:orderId" element={<OrderTracking />} />
                <Route path="login" element={<Login />} />
                <Route path="register" element={<Register />} />
                <Route path="my-orders" element={<MyOrders />} />
              </Route>
              
              {/* Admin Routes (dark theme) */}
              <Route path="/" element={<AdminLayout><Dashboard /></AdminLayout>} />
              <Route path="/catalog" element={<AdminLayout><CatalogPage /></AdminLayout>} />
              <Route path="/inventory" element={<AdminLayout><Inventory /></AdminLayout>} />
              <Route path="/orders" element={<AdminLayout><Orders /></AdminLayout>} />
              <Route path="/production" element={<AdminLayout><Production /></AdminLayout>} />
              <Route path="/logistics" element={<AdminLayout><Logistics /></AdminLayout>} />
              <Route path="/outbox" element={<AdminLayout><Outbox /></AdminLayout>} />
              <Route path="/users" element={<AdminLayout><UsersPage /></AdminLayout>} />
              <Route path="/infrastructure" element={<AdminLayout><Infrastructure /></AdminLayout>} />
            </Routes>
          </BrowserRouter>
        </CartProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
