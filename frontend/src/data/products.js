/**
 * Mock product data for the poster shop
 * In production, this would come from the catalog service
 */

export const products = [
  {
    sku: 'POSTER-SUNSET-A3',
    name: 'Golden Sunset',
    description: 'A breathtaking view of the sun setting over the ocean, painting the sky in shades of orange, pink, and purple.',
    price: 24.99,
    category: 'Nature',
    image: 'https://images.unsplash.com/photo-1507400492013-162706c8c05e?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-MOUNTAIN-A3',
    name: 'Mountain Majesty',
    description: 'Snow-capped peaks rising above the clouds, capturing the raw beauty and power of nature.',
    price: 29.99,
    category: 'Nature',
    image: 'https://images.unsplash.com/photo-1464822759023-fed622ff2c3b?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-CITYNIGHT-A3',
    name: 'City Lights',
    description: 'The vibrant energy of a metropolis at night, with countless lights creating a galaxy on earth.',
    price: 27.99,
    category: 'Urban',
    image: 'https://images.unsplash.com/photo-1519501025264-65ba15a82390?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-FOREST-A3',
    name: 'Enchanted Forest',
    description: 'Sunlight filtering through ancient trees, creating a magical atmosphere in this mystical woodland.',
    price: 24.99,
    category: 'Nature',
    image: 'https://images.unsplash.com/photo-1448375240586-882707db888b?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-OCEAN-A3',
    name: 'Deep Blue',
    description: 'The mesmerizing depths of the ocean, where light dances through crystal clear water.',
    price: 26.99,
    category: 'Nature',
    image: 'https://images.unsplash.com/photo-1518837695005-2083093ee35b?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-ABSTRACT-A3',
    name: 'Color Flow',
    description: 'An explosion of colors blending seamlessly, perfect for adding a modern touch to any space.',
    price: 22.99,
    category: 'Abstract',
    image: 'https://images.unsplash.com/photo-1541701494587-cb58502866ab?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-MINIMAL-A3',
    name: 'Serene Minimalism',
    description: 'Clean lines and subtle tones create a sense of calm and sophistication.',
    price: 21.99,
    category: 'Minimal',
    image: 'https://images.unsplash.com/photo-1494438639946-1ebd1d20bf85?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
  {
    sku: 'POSTER-BOTANICAL-A3',
    name: 'Botanical Garden',
    description: 'Lush greenery and delicate flowers captured in stunning detail.',
    price: 25.99,
    category: 'Nature',
    image: 'https://images.unsplash.com/photo-1459411552884-841db9b3cc2a?w=600&h=800&fit=crop',
    sizes: ['A4', 'A3', 'A2'],
    inStock: true,
  },
];

export const categories = ['All', 'Nature', 'Urban', 'Abstract', 'Minimal'];

export function getProductBySku(sku) {
  return products.find(p => p.sku === sku);
}

export function getProductsByCategory(category) {
  if (category === 'All') return products;
  return products.filter(p => p.category === category);
}

