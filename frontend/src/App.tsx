import { NavLink, Outlet } from "react-router-dom";

import { DemoResetButton } from "./components/DemoResetButton";
import { RuntimeProfileToggle } from "./components/RuntimeProfileToggle";
import { ThemeToggle } from "./components/ThemeToggle";

const NAV = [
  { to: "/", label: "Compromisos", end: true },
  { to: "/reuniones", label: "Reuniones", end: false },
  { to: "/analizar", label: "Analizar", end: false },
  { to: "/preguntar", label: "Preguntar", end: false },
];

function App() {
  return (
    <main className="shell">
      <nav className="nav">
        <div className="nav-left">
          <NavLink to="/" className="nav-wordmark" end aria-label="Quórum">
            <span className="nav-wordmark-mark">Q</span>
            <span className="nav-wordmark-text">uórum</span>
          </NavLink>
          <span className="nav-divider" aria-hidden="true" />
          <div className="nav-links">
            {NAV.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                end={item.end}
                className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}
              >
                {item.label}
              </NavLink>
            ))}
          </div>
        </div>
        <div className="nav-actions">
          <DemoResetButton />
          <RuntimeProfileToggle />
          <ThemeToggle />
        </div>
      </nav>

      <Outlet />
    </main>
  );
}

export default App;
