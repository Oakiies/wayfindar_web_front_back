import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import './index.css';
import ArFusionPoc from './ArFusionPoc.tsx';

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <ArFusionPoc />
  </StrictMode>
);
