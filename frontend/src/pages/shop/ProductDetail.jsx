import { useState } from 'react';
import { useParams, Link, useNavigate } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ShoppingCart, Check, ArrowLeft, Truck, Shield, Undo, Loader2, AlertCircle } from 'lucide-react';
import { useCart } from '../../context/CartContext';
import { catalogApi } from '../../api';

// Fallback to mock data
import { getProductBySku, products as mockProducts } from '../../data/products';

export default function ProductDetail() {
  const { sku } = useParams();
  const navigate = useNavigate();
  const { addItem } = useCart();
  const [quantity, setQuantity] = useState(1);
  const [added, setAdded] = useState(false);
  
  // Fetch product from catalog API
  const { data: apiProduct, isLoading, error } = useQuery({
    queryKey: ['shop-product', sku],
    queryFn: () => catalogApi.getProduct(sku),
    retry: 1,
    staleTime: 30000,
  });
  
  // Fetch related products
  const { data: allProducts } = useQuery({
    queryKey: ['shop-products'],
    queryFn: () => catalogApi.getProducts({ active_only: true }),
    staleTime: 30000,
  });
  
  // Use API product or fallback to mock
  const product = apiProduct || getProductBySku(sku);
  
  // Loading state
  if (isLoading) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 text-center">
        <Loader2 className="w-8 h-8 text-orange-500 animate-spin mx-auto" />
      </div>
    );
  }
  
  // Not found
  if (!product) {
    return (
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-20 text-center">
        <AlertCircle className="w-16 h-16 text-stone-300 mx-auto mb-4" />
        <h1 className="text-2xl font-bold text-stone-900 mb-4">Product not found</h1>
        <Link to="/shop" className="text-orange-600 hover:text-orange-700">
          ← Back to shop
        </Link>
      </div>
    );
  }
  
  // Normalize product fields (API uses image_url, mock uses image)
  const imageUrl = product.image_url || product.image;
  const price = typeof product.price === 'string' ? parseFloat(product.price) : product.price;
  const isInStock = product.in_stock !== false;
  const available = product.available;
  
  const handleAddToCart = () => {
    const cartItem = {
      sku: product.sku,
      name: product.name,
      price: price,
      image: imageUrl,
      description: product.description,
      category: product.category,
    };
    addItem(cartItem, quantity);
    setAdded(true);
    setTimeout(() => setAdded(false), 2000);
  };
  
  const handleBuyNow = () => {
    const cartItem = {
      sku: product.sku,
      name: product.name,
      price: price,
      image: imageUrl,
      description: product.description,
      category: product.category,
    };
    addItem(cartItem, quantity);
    navigate('/shop/checkout');
  };
  
  // Get related products (same category)
  const displayProducts = allProducts || mockProducts;
  const relatedProducts = displayProducts
    .filter(p => p.category === product.category && p.sku !== product.sku)
    .slice(0, 4);
  
  return (
    <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
      {/* Breadcrumb */}
      <nav className="mb-8">
        <Link 
          to="/shop" 
          className="inline-flex items-center gap-2 text-stone-500 hover:text-stone-700 transition-colors"
        >
          <ArrowLeft className="w-4 h-4" />
          Back to Shop
        </Link>
      </nav>
      
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-12">
        {/* Image */}
        <div className="aspect-[3/4] rounded-3xl overflow-hidden bg-stone-100 relative">
          <img
            src={imageUrl}
            alt={product.name}
            className="w-full h-full object-cover"
          />
          {!isInStock && (
            <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
              <span className="px-6 py-3 bg-white text-stone-900 font-semibold rounded-full text-lg">
                Out of Stock
              </span>
            </div>
          )}
        </div>
        
        {/* Details */}
        <div className="lg:py-8">
          <div className="mb-4 flex items-center gap-2">
            <span className="px-3 py-1 bg-orange-100 text-orange-700 text-sm font-medium rounded-full">
              {product.category}
            </span>
            {available !== undefined && available < 10 && available > 0 && (
              <span className="px-3 py-1 bg-amber-100 text-amber-700 text-sm font-medium rounded-full">
                Only {available} left
              </span>
            )}
          </div>
          
          <h1 className="text-4xl font-bold text-stone-900 mb-4">{product.name}</h1>
          
          <p className="text-stone-600 text-lg mb-6">{product.description}</p>
          
          <div className="text-3xl font-bold text-stone-900 mb-8">
            ${price.toFixed(2)}
          </div>
          
          {/* Quantity */}
          <div className="mb-6">
            <label className="block text-sm font-medium text-stone-700 mb-2">
              Quantity
            </label>
            <div className="flex items-center gap-4">
              <button
                onClick={() => setQuantity(Math.max(1, quantity - 1))}
                className="w-10 h-10 rounded-lg border border-stone-200 flex items-center justify-center hover:bg-stone-50 transition-colors"
                disabled={!isInStock}
              >
                -
              </button>
              <span className="text-xl font-semibold w-12 text-center">{quantity}</span>
              <button
                onClick={() => setQuantity(Math.min(available || 99, quantity + 1))}
                className="w-10 h-10 rounded-lg border border-stone-200 flex items-center justify-center hover:bg-stone-50 transition-colors"
                disabled={!isInStock}
              >
                +
              </button>
            </div>
          </div>
          
          {/* Actions */}
          <div className="flex gap-4 mb-8">
            <button
              onClick={handleAddToCart}
              disabled={added || !isInStock}
              className={`
                flex-1 flex items-center justify-center gap-2 py-4 px-6 rounded-xl font-semibold transition-all
                ${!isInStock 
                  ? 'bg-stone-200 text-stone-400 cursor-not-allowed'
                  : added 
                    ? 'bg-green-500 text-white' 
                    : 'bg-stone-100 text-stone-900 hover:bg-stone-200'
                }
              `}
            >
              {added ? (
                <>
                  <Check className="w-5 h-5" />
                  Added!
                </>
              ) : (
                <>
                  <ShoppingCart className="w-5 h-5" />
                  Add to Cart
                </>
              )}
            </button>
            <button
              onClick={handleBuyNow}
              disabled={!isInStock}
              className={`
                flex-1 py-4 px-6 font-semibold rounded-xl transition-all
                ${!isInStock
                  ? 'bg-stone-300 text-stone-500 cursor-not-allowed'
                  : 'bg-gradient-to-r from-orange-500 to-amber-500 text-white hover:from-orange-600 hover:to-amber-600 shadow-lg shadow-orange-500/25'
                }
              `}
            >
              Buy Now
            </button>
          </div>
          
          {/* Features */}
          <div className="grid grid-cols-3 gap-4 py-6 border-t border-b border-stone-200">
            <div className="text-center">
              <Truck className="w-6 h-6 mx-auto text-stone-400 mb-2" />
              <p className="text-sm text-stone-600">Free Shipping</p>
            </div>
            <div className="text-center">
              <Shield className="w-6 h-6 mx-auto text-stone-400 mb-2" />
              <p className="text-sm text-stone-600">Quality Guarantee</p>
            </div>
            <div className="text-center">
              <Undo className="w-6 h-6 mx-auto text-stone-400 mb-2" />
              <p className="text-sm text-stone-600">Easy Returns</p>
            </div>
          </div>
          
          {/* SKU */}
          <div className="mt-6">
            <p className="text-sm text-stone-400">
              SKU: <span className="font-mono">{product.sku}</span>
            </p>
          </div>
        </div>
      </div>
      
      {/* Related Products */}
      {relatedProducts.length > 0 && (
        <div className="mt-20">
          <h2 className="text-2xl font-bold text-stone-900 mb-8">You might also like</h2>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
            {relatedProducts.map((p) => {
              const pImage = p.image_url || p.image;
              const pPrice = typeof p.price === 'string' ? parseFloat(p.price) : p.price;
              return (
                <Link key={p.sku} to={`/shop/product/${p.sku}`} className="group">
                  <div className="aspect-[3/4] rounded-xl overflow-hidden bg-stone-100 mb-3">
                    <img
                      src={pImage}
                      alt={p.name}
                      className="w-full h-full object-cover group-hover:scale-105 transition-transform duration-300"
                    />
                  </div>
                  <h3 className="font-medium text-stone-900 group-hover:text-orange-600 transition-colors">
                    {p.name}
                  </h3>
                  <p className="text-stone-600">${pPrice.toFixed(2)}</p>
                </Link>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
