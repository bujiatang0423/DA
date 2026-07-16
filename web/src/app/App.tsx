import {NavLink,Route,Routes} from "react-router-dom"; import type {FeatureDefinition} from "./featureRegistry";
export function App({features}:{features:readonly FeatureDefinition[]}){return <div><nav>{features.map(f=><NavLink key={f.id} to={f.path}>{f.label}</NavLink>)}</nav><Routes>{features.map(f=><Route key={f.id} path={f.path} element={f.element}/>)}</Routes></div>}
