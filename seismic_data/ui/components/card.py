import streamlit as st

def create_card(title, content_func, *args, **kwargs):
    """
    Creates a styled card container to display content in Streamlit.
    
    Args:
    content_func (callable): A function that generates the content to be displayed inside the card.
    args, kwargs: Arguments and keyword arguments to be passed to content_func.
    """
    with st.container():
        # Unique outer div to control card display
        st.markdown("<div id='chat_outer'></div>", unsafe_allow_html=True)
        
        with st.container():
            # Unique inner div to apply styles
            st.markdown("<div id='chat_inner'></div>", unsafe_allow_html=True)
            
            if title:
                st.markdown(f"<h3 style='margin-left:20px;'>{title}</h3>", unsafe_allow_html=True)
            
            # Execute the function to generate content
            output = content_func(*args, **kwargs)
            
            # Applying CSS styles to the card
            chat_plh_style = """
            <style>
            div[data-testid='stVerticalBlock']:has(div#chat_inner):not(:has(div#chat_outer)) {
                border-radius: 8px; /* Rounded corners */
                box-shadow: 0 4px 8px rgba(0,0,0,0.1); /* Shadow for 3D effect */
                border: 1px solid #ddd; /* Light grey border */
                margin: 10px 0; /* Margin around the card */
            };
            </style>
            """
            st.markdown(chat_plh_style, unsafe_allow_html=True)
    
    script = """<div id = 'chat_outer'></div>"""
    st.markdown(script, unsafe_allow_html=True)
    return output