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
  // null means "not chosen yet" — the first in-stock format is used until then.
  const [sizeName, setSizeName] = useState(null);
  const [frameSku, setFrameSku] = useState(null);
  
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
  
  // The chosen format decides which frames can be offered and what they cost,
  // so this has to be resolved before the frames query runs — and both hooks
  // must sit above the early returns below.
  const apiVariants = apiProduct?.variants ?? [];
  const activeSize =
    sizeName ??
    apiVariants.find((v) => v.in_stock)?.size ??
    apiVariants[0]?.size ??
    null;

  const { data: frameOptions = [] } = useQuery({
    queryKey: ['shop-frames', activeSize],
    queryFn: () => catalogApi.getFrames(activeSize),
    enabled: Boolean(activeSize),
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

  // A family is not sellable; its variants are. Everything below prices and
  // reserves against the chosen variant's own SKU.
  const variants = product.variants ?? [];
  const variant =
    variants.find((v) => v.size === activeSize) ?? variants[0] ?? null;

  // Frames are offered per format, so a colour only appears if it exists in the
  // chosen size, already priced for it.
  const frameChoices = frameOptions.flatMap((f) => f.variants ?? []);
  const frame = frameChoices.find((f) => f.sku === frameSku) ?? null;

  const posterPrice = parseFloat(
    variant?.price ?? product.price_from ?? product.price ?? 0
  );
  const framePrice = frame ? parseFloat(frame.price) : 0;
  const price = posterPrice + framePrice;

  const isInStock = variant ? variant.in_stock !== false : product.in_stock !== false;
  const available = variant ? variant.available : product.available;

  // One order line per physical thing: the poster, and the frame if chosen.
  // Inventory reserves each independently, and the saga already compensates
  // when the poster is available but the frame is not.
  const cartLines = () => {
    const lines = [
      {
        sku: variant?.sku ?? product.sku,
        name: variant ? `${product.name} (${variant.size})` : product.name,
        price: posterPrice,
        image: imageUrl,
        description: product.description,
        category: product.category,
      },
    ];
    if (frame) {
      lines.push({
        sku: frame.sku,
        name: `${frame.frame_name} (${frame.size})`,
        price: framePrice,
        image: imageUrl,
        category: 'Frame',
      });
    }
    return lines;
  };

  const handleAddToCart = () => {
    cartLines().forEach((line) => addItem(line, quantity));
    setAdded(true);
    setTimeout(() => setAdded(false), 2000);
  };
  
  const handleBuyNow = () => {
    cartLines().forEach((line) => addItem(line, quantity));
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
          
          <div className="mb-8">
            <div className="text-3xl font-bold text-stone-900">
              ${price.toFixed(2)}
            </div>
            {frame && (
              <div className="text-sm text-stone-500 mt-1">
                ${posterPrice.toFixed(2)} poster + ${framePrice.toFixed(2)} frame
              </div>
            )}
          </div>

          {/* Format — each is its own SKU with its own price and stock */}
          {variants.length > 0 && (
            <div className="mb-6">
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Format
              </label>
              <div className="flex flex-wrap gap-2">
                {variants.map((v) => {
                  const soldOut = v.in_stock === false;
                  const selected = variant?.sku === v.sku;
                  return (
                    <button
                      key={v.sku}
                      type="button"
                      disabled={soldOut}
                      onClick={() => {
                        setSizeName(v.size);
                        setFrameSku(null); // a frame SKU belongs to one format
                      }}
                      className={`px-4 py-2 rounded-lg border text-sm transition ${
                        selected
                          ? 'border-orange-500 bg-orange-50 text-orange-700'
                          : 'border-stone-300 text-stone-700 hover:border-stone-400'
                      } ${soldOut ? 'opacity-40 cursor-not-allowed line-through' : ''}`}
                    >
                      <span className="font-semibold">{v.size}</span>
                      <span className="block text-xs opacity-70">
                        ${parseFloat(v.price).toFixed(2)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Frame — priced for the chosen format, not a flat surcharge */}
          {frameChoices.length > 0 && (
            <div className="mb-6">
              <label className="block text-sm font-medium text-stone-700 mb-2">
                Frame <span className="font-normal text-stone-400">· optional</span>
              </label>
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  onClick={() => setFrameSku(null)}
                  className={`px-4 py-2 rounded-lg border text-sm transition ${
                    !frame
                      ? 'border-orange-500 bg-orange-50 text-orange-700'
                      : 'border-stone-300 text-stone-700 hover:border-stone-400'
                  }`}
                >
                  <span className="font-semibold">No frame</span>
                  <span className="block text-xs opacity-70">—</span>
                </button>
                {frameChoices.map((f) => {
                  const soldOut = f.in_stock === false;
                  const selected = frame?.sku === f.sku;
                  return (
                    <button
                      key={f.sku}
                      type="button"
                      disabled={soldOut}
                      onClick={() => setFrameSku(f.sku)}
                      className={`px-4 py-2 rounded-lg border text-sm transition ${
                        selected
                          ? 'border-orange-500 bg-orange-50 text-orange-700'
                          : 'border-stone-300 text-stone-700 hover:border-stone-400'
                      } ${soldOut ? 'opacity-40 cursor-not-allowed line-through' : ''}`}
                    >
                      <span className="font-semibold">{f.frame_name}</span>
                      <span className="block text-xs opacity-70">
                        +${parseFloat(f.price).toFixed(2)}
                      </span>
                    </button>
                  );
                })}
              </div>
            </div>
          )}
          
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
              SKU: <span className="font-mono">{variant?.sku ?? product.sku}</span>
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
