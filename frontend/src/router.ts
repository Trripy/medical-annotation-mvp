import { createRouter, createWebHistory } from 'vue-router'

import AnnotationLandingPage from './views/AnnotationLandingPage.vue'
import AnnotatePage from './views/AnnotatePage.vue'
import DatasetsPage from './views/DatasetsPage.vue'
import JobsPage from './views/JobsPage.vue'
import ResearchPage from './views/ResearchPage.vue'
import ResearchVideoAnnotatePage from './views/ResearchVideoAnnotatePage.vue'
import ResearchVideoChecklistPage from './views/ResearchVideoChecklistPage.vue'
import ResearchVideoPhasePage from './views/ResearchVideoPhasePage.vue'
import ResearchVideoSkillPage from './views/ResearchVideoSkillPage.vue'
import ResearchVideoTrimPage from './views/ResearchVideoTrimPage.vue'
import ResearchVideosPage from './views/ResearchVideosPage.vue'
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
      path: '/research',
      component: ResearchPage,
    },
    {
      path: '/research/videos',
      component: ResearchVideosPage,
    },
    {
      path: '/research/videos/checklist',
      component: ResearchVideoChecklistPage,
    },
    {
      path: '/research/videos/:videoId/annotate',
      component: ResearchVideoAnnotatePage,
      props: true,
    },
    {
      path: '/research/videos/:videoId/phases',
      component: ResearchVideoPhasePage,
      props: true,
    },
    {
      path: '/research/videos/:videoId/skills',
      component: ResearchVideoSkillPage,
      props: true,
    },
    {
      path: '/research/videos/:videoId/trim',
      component: ResearchVideoTrimPage,
      props: true,
    },
    {
      path: '/jobs/:jobId/annotate',
      component: AnnotatePage,
      props: true,
    },
  ],
})

export default router
