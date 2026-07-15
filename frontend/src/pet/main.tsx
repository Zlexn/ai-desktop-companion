import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

function PetDevelopmentPlaceholder() {
  return <div aria-label="桌宠开发占位">桌宠开发占位</div>;
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <PetDevelopmentPlaceholder />
  </StrictMode>,
);
