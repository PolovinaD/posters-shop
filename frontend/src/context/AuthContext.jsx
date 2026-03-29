import { createContext, useContext, useState, useEffect } from 'react';
import { usersApi } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const savedToken = localStorage.getItem('shop_token');
    const savedRefreshToken = localStorage.getItem('shop_refresh_token');
    const savedUser = localStorage.getItem('shop_user');

    if (savedToken && savedRefreshToken && savedUser) {
      try {
        setToken(savedToken);
        setUser(JSON.parse(savedUser));
      } catch (e) {
        console.error('Failed to restore auth:', e);
        localStorage.removeItem('shop_token');
        localStorage.removeItem('shop_refresh_token');
        localStorage.removeItem('shop_user');
      }
    } else {
      // Clear partial state
      localStorage.removeItem('shop_token');
      localStorage.removeItem('shop_refresh_token');
      localStorage.removeItem('shop_user');
    }
    setIsLoading(false);
  }, []);

  const login = async (email, password) => {
    const response = await usersApi.login(email, password);
    const { access_token, refresh_token } = response;

    // Store tokens first so authFetchJSON can use them
    localStorage.setItem('shop_token', access_token);
    localStorage.setItem('shop_refresh_token', refresh_token);

    // Fetch user info (getMe now uses authFetchJSON, no token param)
    const userInfo = await usersApi.getMe();

    setToken(access_token);
    setUser(userInfo);
    localStorage.setItem('shop_user', JSON.stringify(userInfo));

    return userInfo;
  };

  const register = async (data) => {
    const response = await usersApi.register(data);
    const { access_token, refresh_token } = response;

    localStorage.setItem('shop_token', access_token);
    localStorage.setItem('shop_refresh_token', refresh_token);

    const userInfo = await usersApi.getMe();

    setToken(access_token);
    setUser(userInfo);
    localStorage.setItem('shop_user', JSON.stringify(userInfo));

    return userInfo;
  };

  const logout = async () => {
    try {
      const refreshToken = localStorage.getItem('shop_refresh_token');
      if (refreshToken) {
        await usersApi.logout(refreshToken);
      }
    } catch (e) {
      // Server-side logout failed -- still clear local state
      console.error('Server logout failed:', e);
    }

    setToken(null);
    setUser(null);
    localStorage.removeItem('shop_token');
    localStorage.removeItem('shop_refresh_token');
    localStorage.removeItem('shop_user');
  };

  const isAuthenticated = !!token && !!user;

  return (
    <AuthContext.Provider
      value={{
        user,
        token,
        isLoading,
        isAuthenticated,
        login,
        register,
        logout,
      }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error('useAuth must be used within an AuthProvider');
  }
  return context;
}
