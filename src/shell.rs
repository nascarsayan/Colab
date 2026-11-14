//! A session-specific prompt without modifying the runtime's global bashrc.
pub fn command(session: &str) -> String {
    let rc = include_str!("shellrc.sh").replace("__COLAB_SESSION__", &crate::quote(session));
    format!("COLAB_SHELL_RC=$(mktemp /tmp/Colab-shell.XXXXXX) && export COLAB_SHELL_RC && printf '%s\\n' {} > \"$COLAB_SHELL_RC\" && exec bash --noprofile --rcfile \"$COLAB_SHELL_RC\" -i",crate::quote(&rc))
}
