{{- define "triage.name" -}}
{{- .Release.Name -}}
{{- end -}}

{{- define "triage.selector" -}}
app.kubernetes.io/name: agent-triage
app.kubernetes.io/instance: {{ .root.Release.Name | quote }}
app.kubernetes.io/component: {{ .component }}
{{- end -}}

{{- define "triage.podSecurity" -}}
automountServiceAccountToken: false
securityContext:
  runAsNonRoot: true
  runAsUser: 10001
  runAsGroup: 10001
  seccompProfile:
    type: RuntimeDefault
{{- with .Values.image.pullSecrets }}
imagePullSecrets:
{{- toYaml . | nindent 2 }}
{{- end }}
{{- end -}}

{{- define "triage.container" -}}
image: {{ printf "%s:%s" (required "image.repository is required" .Values.image.repository) (required "image.tag is required" .Values.image.tag) | quote }}
securityContext:
  allowPrivilegeEscalation: false
  capabilities:
    drop: [ALL]
env:
  - name: TRIAGE_ENV
    value: {{ .Values.environment | quote }}
  - name: TRIAGE_REMEDIATION_MODE
    value: dry_run
  {{- range $key, $value := .Values.config }}
  {{- if has $key (list "TRIAGE_ENV" "TRIAGE_REMEDIATION_MODE" "TRIAGE_DATABASE_URL" "TRIAGE_REDIS_URL") }}
  {{- fail (printf "%s is managed by the chart" $key) }}
  {{- end }}
  - name: {{ $key }}
    value: {{ $value | quote }}
  {{- end }}
  {{- range list "TRIAGE_DATABASE_URL" "TRIAGE_REDIS_URL" }}
  - name: {{ . }}
    valueFrom:
      secretKeyRef:
        name: {{ required "existingSecret is required" $.Values.existingSecret | quote }}
        key: {{ . }}
  {{- end }}
envFrom:
  - secretRef:
      name: {{ .Values.existingSecret | quote }}
{{- end -}}
