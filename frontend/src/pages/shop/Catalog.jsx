import { useState } from 'react';
import { Link } from 'react-router-dom';
import { useQuery } from '@tanstack/react-query';
import { ShoppingCart, Eye, Loader2 } from 'lucide-react';
import { useCart } from '../../context/CartContext';
import { catalogApi } from '../../api';

// Fallback to mock data if API fails
import { products as mockProducts, categories as mockCategories } from '../../data/products';

function ProductCard({ product }) {
  const { addItem, openCart } = useCart();
  const [isHovered, setIsHovered] = useState(false);
  
  const handleAddToCart = (e) => {
    e.preventDefault();
    // Map catalog product to cart item format
    const cartItem = {
      sku: product.sku,
      name: product.name,
      price: parseFloat(product.price),
      image: product.image_url || product.image,
      description: product.description,
      category: product.category,
    };
    addItem(cartItem);
    openCart();
  };
  
  const imageUrl = product.image_url || product.image;
  const price = typeof product.price === 'string' ? parseFloat(product.price) : product.price;
  const isInStock = product.in_stock !== false; // Default to true if not specified
  
  return (
    <div 
      className="group"
      onMouseEnter={() => setIsHovered(true)}
      onMouseLeave={() => setIsHovered(false)}
    >
      <Link to={`/shop/product/${product.sku}`}>
        <div className="relative aspect-[3/4] rounded-2xl overflow-hidden bg-stone-100 mb-4">
          <img
            src={imageUrl}
            alt={product.name}
            className="w-full h-full object-cover transition-transform duration-500 group-hover:scale-105"
          />
          
          {/* Out of stock overlay */}
          {!isInStock && (
            <div className="absolute inset-0 bg-black/40 flex items-center justify-center">
              <span className="px-4 py-2 bg-white text-stone-900 font-medium rounded-full">
                Out of Stock
              </span>
            </div>
          )}
          
          {/* Overlay on hover */}
          {isInStock && (
            <div className={`
              absolute inset-0 bg-gradient-to-t from-black/60 via-transparent to-transparent
              flex items-end justify-center pb-6 transition-opacity duration-300
              ${isHovered ? 'opacity-100' : 'opacity-0'}
            `}>
              <div className="flex gap-2">
                <button
                  onClick={handleAddToCart}
                  className="flex items-center gap-2 px-4 py-2 bg-white text-stone-900 rounded-full font-medium hover:bg-orange-500 hover:text-white transition-colors"
                >
                  <ShoppingCart className="w-4 h-4" />
                  Add to Cart
                </button>
                <Link
                  to={`/shop/product/${product.sku}`}
                  className="p-2 bg-white/20 backdrop-blur-sm text-white rounded-full hover:bg-white hover:text-stone-900 transition-colors"
                >
                  <Eye className="w-5 h-5" />
                </Link>
              </div>
            </div>
          )}
          
          {/* Category badge */}
          <div className="absolute top-4 left-4">
            <span className="px-3 py-1 bg-white/90 backdrop-blur-sm text-xs font-medium text-stone-700 rounded-full">
              {product.category}
            </span>
          </div>
          
          {/* Stock badge */}
          {isInStock && product.available !== undefined && product.available < 10 && (
            <div className="absolute top-4 right-4">
              <span className="px-3 py-1 bg-orange-500 text-white text-xs font-medium rounded-full">
                Only {product.available} left
              </span>
            </div>
          )}
        </div>
      </Link>
      
      <Link to={`/shop/product/${product.sku}`}>
        <h3 className="font-semibold text-stone-900 group-hover:text-orange-600 transition-colors">
          {product.name}
        </h3>
        <p className="text-stone-500 text-sm mt-1 line-clamp-2">{product.description}</p>
        <p className="text-lg font-bold text-stone-900 mt-2">
          ${price.toFixed(2)}
        </p>
      </Link>
    </div>
  );
}

export default function Catalog() {
  const [selectedCategory, setSelectedCategory] = useState('All');
  
  // Fetch products from catalog API
  const { data: products, isLoading: productsLoading, error: productsError } = useQuery({
    queryKey: ['shop-products'],
    queryFn: () => catalogApi.getProducts({ active_only: true, include_stock: true }),
    staleTime: 30000, // 30 seconds
  });
  
  // Fetch categories from catalog API
  const { data: categories } = useQuery({
    queryKey: ['shop-categories'],
    queryFn: catalogApi.getCategories,
    staleTime: 60000, // 1 minute
  });
  
  // Use API data or fallback to mock data
  const displayProducts = products || mockProducts;
  const displayCategories = categories || mockCategories;
  
  const filteredProducts = selectedCategory === 'All' 
    ? displayProducts 
    : displayProducts.filter(p => p.category === selectedCategory);
  
  return (
    <div>
      {/* Hero Section */}
      <div className="relative bg-gradient-to-br from-amber-50 via-orange-50 to-rose-50 py-20 overflow-hidden">
        <div className="absolute inset-0 opacity-30">
          <div className="absolute top-20 left-20 w-64 h-64 bg-orange-300 rounded-full blur-3xl" />
          <div className="absolute bottom-20 right-20 w-96 h-96 bg-amber-300 rounded-full blur-3xl" />
        </div>
        
        <div className="relative max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 text-center">
          <h1 className="text-5xl md:text-6xl font-bold text-stone-900 mb-6">
            Art for Your
            <span className="text-transparent bg-clip-text bg-gradient-to-r from-orange-500 to-amber-500">
              {' '}Walls
            </span>
          </h1>
          <p className="text-xl text-stone-600 max-w-2xl mx-auto">
            Discover our collection of premium art prints. Each poster is printed on 
            museum-quality paper with archival inks.
          </p>
        </div>
      </div>
      
      {/* Category Filter */}
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 py-8">
        <div className="flex flex-wrap gap-2 justify-center">
          {displayCategories.map((category) => (
            <button
              key={category}
              onClick={() => setSelectedCategory(category)}
              className={`
                px-5 py-2 rounded-full text-sm font-medium transition-all
                ${selectedCategory === category
                  ? 'bg-stone-900 text-white shadow-lg'
                  : 'bg-white text-stone-600 hover:bg-stone-100 border border-stone-200'
                }
              `}
            >
              {category}
            </button>
          ))}
        </div>
      </div>
      
      {/* Loading State */}
      {productsLoading && (
        <div className="flex items-center justify-center py-20">
          <Loader2 className="w-8 h-8 text-orange-500 animate-spin" />
        </div>
      )}
      
      {/* Error State - show fallback data */}
      {productsError && !productsLoading && (
        <div className="max-w-7xl mx-auto px-4 text-center py-4">
          <p className="text-amber-600 text-sm">
            Live catalog unavailable, showing sample products.
          </p>
        </div>
      )}
      
      {/* Product Grid */}
      {!productsLoading && (
        <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pb-20">
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-8">
            {filteredProducts.map((product) => (
              <ProductCard key={product.sku} product={product} />
            ))}
          </div>
          
          {filteredProducts.length === 0 && (
            <div className="text-center py-20">
              <p className="text-stone-500">No products found in this category.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
