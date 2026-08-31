import { create } from 'zustand';
import { devtools } from 'zustand/middleware';

type AppState = {
    user: any | null;
    isUserLoaded: boolean;
    setUser: (user: any | null) => void;
    setIsUserLoaded: (loaded: boolean) => void;
};

export const useAppStore = create<AppState>()(
    devtools(
        (set) => ({
            user: null,
            isUserLoaded: false,
            setUser: (user) => set({ user }),
            setIsUserLoaded: (loaded) => set({ isUserLoaded: loaded }),
        }),
        {
            name: 'AppStore',
            enabled: process.env.NODE_ENV !== 'production'
        }
    )
);
