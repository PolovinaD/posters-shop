import { Link, Outlet, useLocation } from 'react-router-dom';
import { ShoppingCart, Package, Menu, X, User, LogOut, ChevronDown } from 'lucide-react';
import { useState, useEffect, useRef } from 'react';
import { useCart } from '../../context/CartContext';
import { useAuth } from '../../context/AuthContext';
import CartDrawer from './CartDrawer';

export default function ShopLayout() {
  const [mobileMenuOpen, setMobileMenuOpen] = useState(false);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const userMenuRef = useRef(null);
  const { itemCount, toggleCart } = useCart();
  const { user, isAuthenticated, logout } = useAuth();
  const location = useLocation();

  useEffect(() => {
    function handleClickOutside(event) {
      if (userMenuRef.current && !userMenuRef.current.contains(event.target)) {
        setUserMenuOpen(false);
      }
    }
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);
  
  // Update page title for shop pages
  useEffect(() => {
    const titles = {
      '/shop': 'PosterShop - Art Prints for Your Walls',
      '/shop/checkout': 'Checkout - PosterShop',
      '/shop/orders': 'Track Order - PosterShop',
    };
    
    if (location.pathname.startsWith('/shop/product/')) {
      document.title = 'Product - PosterShop';
    } else if (location.pathname.startsWith('/shop/orders/')) {
      document.title = 'Order Tracking - PosterShop';
    } else {
      document.title = titles[location.pathname] || 'PosterShop';
    }
  }, [location.pathname]);
  
  return (
    <div className="min-h-screen bg-[#faf9f7] shop-light-mode text-stone-900">
      {/* Header */}
      <header className="sticky top-0 z-40 bg-white/80 backdrop-blur-md border-b border-stone-200">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
          <div className="flex items-center justify-between h-16">
            {/* Logo */}
            <Link to="/shop" className="flex items-center gap-2">
              <div className="w-10 h-10 rounded-xl bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center shadow-lg shadow-orange-500/20">
                <Package className="w-5 h-5 text-white" />
              </div>
              <span className="text-xl font-bold text-stone-900">PosterShop</span>
            </Link>
            
            {/* Desktop Nav */}
            <nav className="hidden md:flex items-center gap-8">
              <Link 
                to="/shop" 
                className={`text-sm font-medium transition-colors ${
                  location.pathname === '/shop' 
                    ? 'text-orange-600' 
                    : 'text-stone-600 hover:text-stone-900'
                }`}
              >
                Shop
              </Link>
              {isAuthenticated ? (
                <Link 
                  to="/shop/my-orders" 
                  className={`text-sm font-medium transition-colors ${
                    location.pathname === '/shop/my-orders'
                      ? 'text-orange-600' 
                      : 'text-stone-600 hover:text-stone-900'
                  }`}
                >
                  My Orders
                </Link>
              ) : (
                <Link 
                  to="/shop/orders" 
                  className={`text-sm font-medium transition-colors ${
                    location.pathname.startsWith('/shop/orders')
                      ? 'text-orange-600' 
                      : 'text-stone-600 hover:text-stone-900'
                  }`}
                >
                  Track Order
                </Link>
              )}
              <Link 
                to="/" 
                className="text-sm font-medium text-stone-400 hover:text-stone-600 transition-colors"
              >
                Admin
              </Link>
            </nav>
            
            {/* Actions */}
            <div className="flex items-center gap-2">
              {/* User menu */}
              {isAuthenticated ? (
                <div className="relative hidden md:block" ref={userMenuRef}>
                  <button
                    onClick={() => setUserMenuOpen(!userMenuOpen)}
                    className="flex items-center gap-2 px-3 py-2 rounded-lg text-stone-600 hover:bg-stone-100 transition-colors"
                  >
                    <div className="w-8 h-8 rounded-full bg-gradient-to-br from-orange-400 to-amber-500 flex items-center justify-center text-white text-sm font-medium">
                      {user?.name?.[0]?.toUpperCase() || 'U'}
                    </div>
                    <span className="text-sm font-medium">{user?.name?.split(' ')[0]}</span>
                    <ChevronDown className={`w-4 h-4 transition-transform ${userMenuOpen ? 'rotate-180' : ''}`} />
                  </button>

                  {userMenuOpen && (
                    <div className="absolute right-0 mt-2 w-48 bg-white rounded-xl shadow-lg border border-stone-200 py-2 z-50">
                      <div className="px-4 py-2 border-b border-stone-100">
                        <p className="text-sm font-medium text-stone-900">{user?.name}</p>
                        <p className="text-xs text-stone-500 truncate">{user?.email}</p>
                      </div>
                      <Link
                        to="/shop/my-orders"
                        onClick={() => setUserMenuOpen(false)}
                        className="flex items-center gap-2 px-4 py-2 text-sm text-stone-600 hover:bg-stone-50"
                      >
                        <Package className="w-4 h-4" />
                        My Orders
                      </Link>
                      <button
                        onClick={() => {
                          logout();
                          setUserMenuOpen(false);
                        }}
                        className="flex items-center gap-2 w-full px-4 py-2 text-sm text-red-600 hover:bg-red-50"
                      >
                        <LogOut className="w-4 h-4" />
                        Sign Out
                      </button>
                    </div>
                  )}
                </div>
              ) : (
                <Link
                  to="/shop/login"
                  className="hidden md:flex items-center gap-2 px-4 py-2 text-sm font-medium text-stone-600 hover:text-stone-900 transition-colors"
                >
                  <User className="w-4 h-4" />
                  Sign In
                </Link>
              )}

              <button
                onClick={toggleCart}
                className="relative p-2 text-stone-600 hover:text-stone-900 transition-colors"
              >
                <ShoppingCart className="w-6 h-6" />
                {itemCount > 0 && (
                  <span className="absolute -top-1 -right-1 w-5 h-5 bg-orange-500 text-white text-xs font-bold rounded-full flex items-center justify-center">
                    {itemCount}
                  </span>
                )}
              </button>
              
              {/* Mobile menu button */}
              <button
                onClick={() => setMobileMenuOpen(!mobileMenuOpen)}
                className="md:hidden p-2 text-stone-600"
              >
                {mobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
              </button>
            </div>
          </div>
        </div>
        
        {/* Mobile Nav */}
        {mobileMenuOpen && (
          <div className="md:hidden border-t border-stone-200 bg-white">
            <nav className="px-4 py-4 space-y-2">
              {isAuthenticated && (
                <div className="px-4 py-3 mb-2 bg-stone-50 rounded-lg">
                  <p className="text-sm font-medium text-stone-900">{user?.name}</p>
                  <p className="text-xs text-stone-500">{user?.email}</p>
                </div>
              )}
              <Link 
                to="/shop"
                onClick={() => setMobileMenuOpen(false)}
                className="block px-4 py-2 rounded-lg text-stone-600 hover:bg-stone-100"
              >
                Shop
              </Link>
              {isAuthenticated ? (
                <Link 
                  to="/shop/my-orders"
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-4 py-2 rounded-lg text-stone-600 hover:bg-stone-100"
                >
                  My Orders
                </Link>
              ) : (
                <Link 
                  to="/shop/orders"
                  onClick={() => setMobileMenuOpen(false)}
                  className="block px-4 py-2 rounded-lg text-stone-600 hover:bg-stone-100"
                >
                  Track Order
                </Link>
              )}
              <Link 
                to="/"
                onClick={() => setMobileMenuOpen(false)}
                className="block px-4 py-2 rounded-lg text-stone-400 hover:bg-stone-100"
              >
                Admin Dashboard
              </Link>
              <div className="border-t border-stone-200 pt-2 mt-2">
                {isAuthenticated ? (
                  <button
                    onClick={() => {
                      logout();
                      setMobileMenuOpen(false);
                    }}
                    className="block w-full text-left px-4 py-2 rounded-lg text-red-600 hover:bg-red-50"
                  >
                    Sign Out
                  </button>
                ) : (
                  <>
                    <Link 
                      to="/shop/login"
                      onClick={() => setMobileMenuOpen(false)}
                      className="block px-4 py-2 rounded-lg text-orange-600 hover:bg-orange-50"
                    >
                      Sign In
                    </Link>
                    <Link 
                      to="/shop/register"
                      onClick={() => setMobileMenuOpen(false)}
                      className="block px-4 py-2 rounded-lg text-stone-600 hover:bg-stone-100"
                    >
                      Create Account
                    </Link>
                  </>
                )}
              </div>
            </nav>
          </div>
        )}
      </header>
      
      {/* Main Content */}
      <main>
        <Outlet />
      </main>
      
      {/* Footer */}
      <footer className="bg-stone-900 text-stone-400 mt-20">
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-12">
          <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
            <div>
              <div className="flex items-center gap-2 mb-4">
                <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-amber-400 to-orange-500 flex items-center justify-center">
                  <Package className="w-4 h-4 text-white" />
                </div>
                <span className="text-lg font-bold text-white">PosterShop</span>
              </div>
              <p className="text-sm">
                Beautiful art prints for your space. Designed with passion, printed with precision.
              </p>
            </div>
            <div>
              <h4 className="font-semibold text-white mb-4">Quick Links</h4>
              <ul className="space-y-2 text-sm">
                <li><Link to="/shop" className="hover:text-white transition-colors">Shop All</Link></li>
                <li><Link to="/shop/orders" className="hover:text-white transition-colors">Track Order</Link></li>
              </ul>
            </div>
            <div>
              <h4 className="font-semibold text-white mb-4">Demo Project</h4>
              <p className="text-sm">
                This is a demo e-commerce platform showcasing microservices architecture.
              </p>
            </div>
          </div>
          <div className="border-t border-stone-800 mt-8 pt-8 text-center text-sm">
            <p>© 2024 PosterShop. Built for demonstration purposes.</p>
          </div>
        </div>
      </footer>
      
      {/* Cart Drawer */}
      <CartDrawer />
    </div>
  );
}

