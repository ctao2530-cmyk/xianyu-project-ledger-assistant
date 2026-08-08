import type { Project, ProjectKind } from "../types";

/** Legacy projects were all customer projects, so missing values remain client projects. */
export const projectKindOf = (project: Project): ProjectKind =>
  project.projectKind === "personal" ? "personal" : "client";

export const isClientProject = (project: Project) => projectKindOf(project) === "client";
