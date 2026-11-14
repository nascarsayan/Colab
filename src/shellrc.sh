# This rcfile is private to the connected shell and can be removed after loading.
if [[ -n ${COLAB_SHELL_RC:-} ]]; then
    rm -f -- "$COLAB_SHELL_RC"
    unset COLAB_SHELL_RC
fi
if [[ $- == *i* && -r ~/.bashrc ]]; then
    source ~/.bashrc
fi

__colab_session=__COLAB_SESSION__
__colab_prompt() {
    local status=$?
    local cwd="${PWD%/}" parent leaf display
    if [[ -z $cwd ]]; then
        display=/
    else
        leaf=${cwd##*/}
        parent=${cwd%/*}
        if [[ -n $parent && $parent != "$cwd" && $parent != / ]]; then
            display="${parent##*/}/$leaf"
        else
            display=$leaf
        fi
    fi
    # Escape prompt backslashes; disable second-pass expansion of directory text.
    # A directory containing $(...) must never execute commands via the prompt.
    display=${display//\\/\\\\}
    if [[ -z ${NO_COLOR:-} && ${TERM:-dumb} != dumb ]]; then
        local cyan='\[\e[1;36m\]' blue='\[\e[1;34m\]' reset='\[\e[0m\]'
        local dollar='\[\e[1;32m\]'
        if (( status != 0 )); then dollar='\[\e[1;31m\]'; fi
        # Readline must ignore escape-sequence widths when editing/wrapping lines.
        printf -v PS1 '%s(%s)%s %s%s%s %s$%s ' "$cyan" "$__colab_session" "$reset" "$blue" "$display" "$reset" "$dollar" "$reset"
    else
        printf -v PS1 '(%s) %s $ ' "$__colab_session" "$display"
    fi
}
shopt -u promptvars
unset PROMPT_COMMAND
PROMPT_COMMAND=__colab_prompt
__colab_prompt
