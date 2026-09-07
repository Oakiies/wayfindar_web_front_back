import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import ArVideoLocalizePoc from './ArVideoLocalizePoc.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ArVideoLocalizePoc />
  </StrictMode>
);
