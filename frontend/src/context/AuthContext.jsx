import { createContext, useContext, useState, useEffect } from 'react';
import { usersApi } from '../api';

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    const savedToken = localStorage.getItem('shop_token');
    const savedUser = localStorage.getItem('shop_user');
    
    if (savedToken && savedUser) {
      try {
        setToken(savedToken);
        setUser(JSON.parse(savedUser));
      } catch (e) {
        console.error('Failed to restore auth:', e);
        localStorage.removeItem('shop_token');
        localStorage.removeItem('shop_user');
      }
    }
    setIsLoading(false);
  }, []);

  const login = async (email, password) => {
    const response = await usersApi.login(email, password);
    const { access_token } = response;
    
    const userInfo = await usersApi.getMe(access_token);
    
    setToken(access_token);
    setUser(userInfo);
    
    localStorage.setItem('shop_token', access_token);
    localStorage.setItem('shop_user', JSON.stringify(userInfo));
    
    return userInfo;
  };

  const register = async (data) => {
    await usersApi.register(data);
    return login(data.email, data.password);
  };

  const logout = () => {
    setToken(null);
    setUser(null);
    localStorage.removeItem('shop_token');
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
