import { commissioningRoutes } from './routes/commissioning';
import { configurationRoutes } from './routes/configuration';
import { cultivationRoutes } from './routes/cultivation';
import { economicsRoutes } from './routes/economics';
import { membersRoutes } from './routes/members';
import { staffRoutes } from './routes/staff';
import { warehouseRoutes } from './routes/warehouse';
import { abosRoutes } from './routes/abos';
import type { RouteGroup } from './types';

export const routeGroups: RouteGroup[] = [
  {
    path: '/members',
    feature: 'members', 
    routes: membersRoutes
  },
  {
    path: '/abos',
    feature: 'abos', 
    routes: abosRoutes
  },
  {
    path: '/commissioning',
    feature: 'commissioning',
    routes: commissioningRoutes
  },
    {
    path: '/staff',
    feature: 'staff', 
    routes: staffRoutes
  },
  {
    path: '/warehouse',
    feature: 'warehouse',
    routes: warehouseRoutes
  },
   {
    path: '/economics',
    feature: 'economics', 
    routes: economicsRoutes
  },
    {
    path: '/cultivation',
    feature: 'cultivation', 
    routes: cultivationRoutes
  },

  {
    path: '/configuration',
    feature: 'configuration',
    routes: configurationRoutes
  },



];
