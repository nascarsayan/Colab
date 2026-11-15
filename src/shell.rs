//! A session-specific prompt without modifying the runtime's global bashrc.
pub fn command(session: &str) -> String {
    let label = std::env::var("COLAB_ACCOUNT")
        .map(|email| {
            format!(
                "{}@{session}",
                email
                    .split_once('@')
                    .map(|(user, _)| user)
                    .unwrap_or(&email)
            )
        })
        .unwrap_or_else(|_| session.to_owned());
    let rc = include_str!("shellrc.sh").replace("__COLAB_SESSION__", &crate::quote(&label));
    format!("COLAB_SHELL_RC=$(mktemp /tmp/Colab-shell.XXXXXX) && export COLAB_SHELL_RC && printf '%s\\n' {} > \"$COLAB_SHELL_RC\" && exec bash --noprofile --rcfile \"$COLAB_SHELL_RC\" -i",crate::quote(&rc))
}
