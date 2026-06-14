import { createRouter, createWebHistory } from 'vue-router'

import AnnotationLandingPage from './views/AnnotationLandingPage.vue'
import AnnotatePage from './views/AnnotatePage.vue'
import DatasetsPage from './views/DatasetsPage.vue'
import JobsPage from './views/JobsPage.vue'
import ReviewPage from './views/ReviewPage.vue'

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: '/',
      redirect: '/jobs',
    },
    {
      path: '/jobs',
      component: JobsPage,
    },
    {
      path: '/jobs/projects/:projectId',
      component: JobsPage,
      props: true,
    },
    {
      path: '/datasets',
      component: DatasetsPage,
    },
    {
      path: '/annotation',
      component: AnnotationLandingPage,
    },
    {
      path: '/review',
      component: ReviewPage,
    },
    {
      path: '/jobs/:jobId/annotate',
      component: AnnotatePage,
      props: true,
    },
  ],
})

export default router
